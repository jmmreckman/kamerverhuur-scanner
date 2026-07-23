"""Documenten opvragen bij een kandidaat-huurder na de bezichtiging: de
beheerder kiest de gekozen kandidaat op de bezichtigingen-pagina en stuurt
een mail met een unieke, niet te raden link (net als bij het elektronisch
ondertekenen, zie webapp/ondertekenen.py) waarop de kandidaat een kopie van
zijn/haar ID/paspoort en bewijs van inkomen/garantsteller kan uploaden.

De stand van zaken per verzoek staat in een JSON-bestand (STATE_DIR/
documentverzoeken/<pand>/<sleutel>.json) - de sleutel is een deterministische
slug van kamer+naam+email (zie maak_sleutel()), zodat een nieuw verzoek voor
dezelfde kandidaat altijd hetzelfde bestand (en dezelfde upload-map, zie
kamerverhuur_scanner/lokale_media.py) hergebruikt in plaats van een dubbele
aan te maken. Een los indexbestand (STATE_DIR/documentverzoektokens.json)
koppelt elke token aan het bijbehorende pand/sleutel, zodat de publieke
/documenten/<token>-pagina die in één keer kan opzoeken zonder alle panden
te hoeven doorzoeken."""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime
from pathlib import Path

from kamerverhuur_scanner.models import Pand

from .reminders import AFZENDER_NAAM


def _slugify(tekst: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", tekst.lower()).strip("-") or "onbekend"


def maak_sleutel(kamer: str, naam: str, email: str) -> str:
    return _slugify(f"{kamer}-{naam}-{email}")


def _verzoek_pad(pand_slug: str, sleutel: str, state_dir: str) -> Path:
    return Path(state_dir) / "documentverzoeken" / _slugify(pand_slug) / f"{sleutel}.json"


def _index_pad(state_dir: str) -> Path:
    return Path(state_dir) / "documentverzoektokens.json"


def _lees_index(state_dir: str) -> dict:
    pad = _index_pad(state_dir)
    if not pad.is_file():
        return {}
    try:
        return json.loads(pad.read_text())
    except json.JSONDecodeError:
        return {}


def _schrijf_index(state_dir: str, index: dict) -> None:
    pad = _index_pad(state_dir)
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text(json.dumps(index))


def lees_verzoek(pand_slug: str, sleutel: str, state_dir: str = ".") -> dict | None:
    """De stand van zaken van dit documentverzoek, of None als er (nog) geen
    verzoek voor deze kandidaat is aangemaakt."""
    pad = _verzoek_pad(pand_slug, sleutel, state_dir)
    if not pad.is_file():
        return None
    return json.loads(pad.read_text())


def _schrijf_verzoek(pand_slug: str, sleutel: str, state_dir: str, verzoek: dict) -> None:
    pad = _verzoek_pad(pand_slug, sleutel, state_dir)
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text(json.dumps(verzoek))


def start_documentverzoek(
    pand_slug: str, kamer: str, naam: str, email: str, telefoon: str, state_dir: str = ".",
) -> dict:
    """Zet een nieuw documentverzoek op voor deze kandidaat, of geeft het
    bestaande terug als er al eerder een verzoek voor dezelfde kamer+naam+
    email is aangemaakt (idempotent, zie maak_sleutel()) - zodat het
    voorbeeldscherm altijd de echte, al aangemaakte upload-link toont en een
    dubbele klik geen nieuw token genereert. Verstuurt zelf geen mail (dat
    gebeurt pas na bevestiging op het voorbeeldscherm, zie markeer_verzonden()
    hieronder)."""
    sleutel = maak_sleutel(kamer, naam, email)
    bestaand = lees_verzoek(pand_slug, sleutel, state_dir)
    if bestaand is not None:
        return bestaand

    verzoek = {
        "pand_slug": pand_slug, "sleutel": sleutel, "kamer": kamer, "naam": naam,
        "email": email, "telefoon": telefoon, "token": secrets.token_urlsafe(32),
        "aangemaakt_op": datetime.now().isoformat(timespec="seconds"),
        "verzonden_op": None, "documenten": [], "ontvangen_op": None,
    }
    _schrijf_verzoek(pand_slug, sleutel, state_dir, verzoek)

    index = _lees_index(state_dir)
    index[verzoek["token"]] = {"pand_slug": pand_slug, "sleutel": sleutel}
    _schrijf_index(state_dir, index)
    return verzoek


def markeer_verzonden(pand_slug: str, sleutel: str, state_dir: str = ".") -> dict:
    verzoek = lees_verzoek(pand_slug, sleutel, state_dir)
    verzoek["verzonden_op"] = datetime.now().isoformat(timespec="seconds")
    _schrijf_verzoek(pand_slug, sleutel, state_dir, verzoek)
    return verzoek


def zoek_via_token(token: str, state_dir: str = ".") -> tuple[str, dict] | None:
    """Geeft (pand_slug, verzoek) terug voor deze token, of None als de token
    onbekend is."""
    verwijzing = _lees_index(state_dir).get(token)
    if verwijzing is None:
        return None
    verzoek = lees_verzoek(verwijzing["pand_slug"], verwijzing["sleutel"], state_dir)
    if verzoek is None:
        return None
    return verwijzing["pand_slug"], verzoek


def voeg_documenten_toe(pand_slug: str, sleutel: str, documenten: list[dict], state_dir: str = ".") -> dict:
    """Voegt geuploade bestanden (elk {"categorie", "bestand_id", "naam",
    "mimetype"}) toe aan dit verzoek en markeert het als (deels) ontvangen -
    een kandidaat kan in principe meerdere keren uploaden (bv. eerst het ID,
    later alsnog het inkomensbewijs), dus dit vervangt de lijst niet maar
    vult 'm aan."""
    verzoek = lees_verzoek(pand_slug, sleutel, state_dir)
    if verzoek is None:
        raise ValueError(f"Geen documentverzoek gevonden voor '{sleutel}'.")
    verzoek["documenten"].extend(documenten)
    verzoek["ontvangen_op"] = datetime.now().isoformat(timespec="seconds")
    _schrijf_verzoek(pand_slug, sleutel, state_dir, verzoek)
    return verzoek


def bouw_documentverzoek_mail(pand: Pand, kamer: str, naam: str, upload_url: str) -> dict[str, str]:
    """Stelt de (Engelstalige) mail op waarmee, na de bezichtiging, om
    documenten wordt gevraagd bij de gekozen kandidaat-huurder - de beheerder
    kan dit nog aanpassen op het voorbeeldscherm, net als bij de andere
    mails in deze site."""
    naam_of_daar = naam or "there"
    onderwerp = f"Documents needed - room {kamer}, {pand.naam}".strip()
    tekst = (
        f"Dear {naam_of_daar},\n\n"
        f"Great news - following our viewing, we would love to welcome you as the new tenant for "
        f"room {kamer} at {pand.naam}!\n\n"
        f"To draw up the draft rental agreement, could you please upload the following documents "
        f"via the secure link below:\n\n"
        f"   - A copy of your ID card or passport\n"
        f"   - Proof of income (payslip/employment contract) or, if applicable, your guarantor's "
        f"proof of income\n\n"
        f"{upload_url}\n\n"
        f"Once we have received everything, we will prepare the draft rental agreement for you.\n\n"
        f"Kind regards,\n{AFZENDER_NAAM}"
    )
    return {"onderwerp": onderwerp, "tekst": tekst}

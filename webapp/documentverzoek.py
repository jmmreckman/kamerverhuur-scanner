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


# Vragen op de publieke pagina bij een directe aanvraag (huurder rechtstreeks
# gevonden, geen bezichtiging - dus geen aanmelding in het systeem). Alleen de
# contract-relevante velden uit het gewone aanmeldformulier; de bezichtiging-
# vragen (videobellen, voorkeursmomenten) slaan hier nergens op. Engelstalig,
# net als de rest van de publieke uploadpagina. `key` komt overeen met wat er in
# verzoek["aanvraag_gegevens"] bewaard wordt.
AANVRAAG_VELDEN = [
    ("huidig_adres", "Your current address"),
    ("studie", "Study / field of study"),
    ("studentnummer", "Student number"),
    ("gewenste_ingangsdatum", "Preferred start date"),
    ("gewenste_huurduur", "Desired rental duration"),
    ("inkomstenbron", "Source of income (job, study finance, parents, ...)"),
    ("inkomsten_bedrag", "Approximate monthly income"),
    ("borgsteller_naam", "Guarantor name (if applicable)"),
    ("borgsteller_relatie", "Guarantor relation to you (if applicable)"),
    ("borgsteller_email", "Guarantor email (if applicable)"),
]


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


def list_verzoeken(pand_slug: str, state_dir: str = ".") -> list[dict]:
    """Alle documentverzoeken van dit pand, nieuwste eerst - voor het
    overzichtsscherm (zie webapp/app.py: documentverzoeken_overzicht()),
    want zonder dit scherm is een verzoek alleen terug te vinden via de
    link in de meldingsmail."""
    map_pad = Path(state_dir) / "documentverzoeken" / _slugify(pand_slug)
    if not map_pad.is_dir():
        return []
    verzoeken = []
    for bestand in map_pad.glob("*.json"):
        try:
            verzoeken.append(json.loads(bestand.read_text()))
        except json.JSONDecodeError:
            continue
    verzoeken.sort(key=lambda v: v.get("aangemaakt_op") or "", reverse=True)
    return verzoeken


def _schrijf_verzoek(pand_slug: str, sleutel: str, state_dir: str, verzoek: dict) -> None:
    pad = _verzoek_pad(pand_slug, sleutel, state_dir)
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text(json.dumps(verzoek))


def start_documentverzoek(
    pand_slug: str, kamer: str, naam: str, email: str, telefoon: str, state_dir: str = ".",
    direct: bool = False,
) -> dict:
    """Zet een nieuw documentverzoek op voor deze kandidaat, of geeft het
    bestaande terug als er al eerder een verzoek voor dezelfde kamer+naam+
    email is aangemaakt (idempotent, zie maak_sleutel()) - zodat het
    voorbeeldscherm altijd de echte, al aangemaakte upload-link toont en een
    dubbele klik geen nieuw token genereert. Verstuurt zelf geen mail (dat
    gebeurt pas na bevestiging op het voorbeeldscherm, zie markeer_verzonden()
    hieronder).

    `direct=True` markeert een rechtstreekse aanvraag (huurder via-via gevonden,
    geen bezichtiging): de publieke pagina toont dan óók de vragenlijst (zie
    AANVRAAG_VELDEN), zodat er geen aparte aanmelding nodig is."""
    sleutel = maak_sleutel(kamer, naam, email)
    bestaand = lees_verzoek(pand_slug, sleutel, state_dir)
    if bestaand is not None:
        return bestaand

    verzoek = {
        "pand_slug": pand_slug, "sleutel": sleutel, "kamer": kamer, "naam": naam,
        "email": email, "telefoon": telefoon, "token": secrets.token_urlsafe(32),
        "aangemaakt_op": datetime.now().isoformat(timespec="seconds"),
        "verzonden_op": None, "documenten": [], "ontvangen_op": None,
        "ai_resultaat": None, "mismatches": [], "concept_contract_bestandsnaam": None,
        "direct": direct, "aanvraag_gegevens": None,
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


def zet_aanvraag_gegevens(pand_slug: str, sleutel: str, gegevens: dict, state_dir: str = ".") -> dict:
    """Bewaart de door de huurder ingevulde vragenlijst (bij een directe
    aanvraag) op het verzoek, zodat het concept-huurcontract die kan gebruiken
    (er is immers geen aanmelding in het systeem)."""
    verzoek = lees_verzoek(pand_slug, sleutel, state_dir)
    if verzoek is None:
        raise ValueError(f"Geen documentverzoek gevonden voor '{sleutel}'.")
    verzoek["aanvraag_gegevens"] = gegevens
    _schrijf_verzoek(pand_slug, sleutel, state_dir, verzoek)
    return verzoek


def zet_ai_resultaat(
    pand_slug: str, sleutel: str, ai_resultaat: dict | None, mismatches: list[str],
    concept_contract_bestandsnaam: str | None, state_dir: str = ".",
) -> dict:
    """Legt vast wat de AI-uitlezing van de documenten heeft opgeleverd (zie
    kamerverhuur_scanner/document_ai.py), eventuele afwijkingen t.o.v. de
    aanmelding, en de bestandsnaam van het automatisch gegenereerde concept-
    huurcontract (indien gelukt) - zichtbaar op de documentverzoek-statuspagina."""
    verzoek = lees_verzoek(pand_slug, sleutel, state_dir)
    if verzoek is None:
        raise ValueError(f"Geen documentverzoek gevonden voor '{sleutel}'.")
    verzoek["ai_resultaat"] = ai_resultaat
    verzoek["mismatches"] = mismatches
    verzoek["concept_contract_bestandsnaam"] = concept_contract_bestandsnaam
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


def bouw_directe_aanvraag_mail(pand: Pand, kamer: str, naam: str, upload_url: str) -> dict[str, str]:
    """Mail voor een rechtstreeks (via-via) gevonden huurder, zonder bezichtiging:
    op één pagina vult ze haar gegevens in én uploadt ze haar documenten, zodat
    het concept-huurcontract opgesteld kan worden. Aanpasbaar op het
    voorbeeldscherm, net als de andere mails."""
    naam_of_daar = naam or "there"
    onderwerp = f"Your details for room {kamer}, {pand.naam}".strip()
    tekst = (
        f"Dear {naam_of_daar},\n\n"
        f"Welcome as the new tenant for room {kamer} at {pand.naam}!\n\n"
        f"To draw up the draft rental agreement, could you please fill in your details and upload a "
        f"few documents via the secure link below? It takes just a couple of minutes:\n\n"
        f"   - Your details (address, study, start date, income, guarantor if any)\n"
        f"   - A copy of your ID card or passport\n"
        f"   - Proof of income (or your guarantor's), and proof of enrolment if you are a student\n\n"
        f"{upload_url}\n\n"
        f"Once we have received everything, we will prepare the draft rental agreement for you.\n\n"
        f"Kind regards,\n{AFZENDER_NAAM}"
    )
    return {"onderwerp": onderwerp, "tekst": tekst}

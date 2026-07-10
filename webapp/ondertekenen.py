"""Elektronisch laten ondertekenen van een gegenereerd huurcontract.

De huurder, de verhuurder(s) van het pand en (indien bekend) de borgsteller
krijgen elk een eigen unieke, niet te raden link om te tekenen (zie
webapp/app.py: /tekenen/<token>). Zodra iedereen getekend heeft, wordt
automatisch de definitieve ondertekende versie gemaakt (zie
contracts.genereer_getekend_contract()) en gemaild aan alle partijen.

Elke ondertekening legt een audit-trail vast: tijdstip, IP-adres, user-agent
en de expliciet getypte naam. Dit is een "gewone" elektronische handtekening
(SES onder de eIDAS-verordening) - voor een tijdelijk kamerhuurcontract is
dat in Nederland rechtsgeldig, mits goed gedocumenteerd zoals hier.

De stand van zaken per contract (wie heeft al getekend) staat in een JSON-
bestand naast het contract zelf (STATE_DIR/gegenereerde_contracten/<pand>/
<bestandsnaam>.ondertekening.json). Een los indexbestand (STATE_DIR/
ondertekentokens.json) koppelt elke token aan het bijbehorende pand/contract,
zodat de publieke /tekenen/<token>-pagina die in één keer kan opzoeken zonder
alle panden te hoeven doorzoeken."""
from __future__ import annotations

import calendar
import html
import json
import secrets
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from kamerverhuur_scanner.models import Pand

from . import contracts
from .reminders import AFZENDER_NAAM

_ROLNAMEN_EN = {"huurder": "tenant", "verhuurder": "landlord", "borgsteller": "guarantor"}


def _ronde_pad(pand_slug: str, bestandsnaam: str, state_dir: str) -> Path:
    return contracts.output_dir(pand_slug, state_dir) / f"{Path(bestandsnaam).name}.ondertekening.json"


def _index_pad(state_dir: str) -> Path:
    return Path(state_dir) / "ondertekentokens.json"


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


def lees_ondertekenronde(pand_slug: str, bestandsnaam: str, state_dir: str = ".") -> dict | None:
    """De stand van zaken van de ondertekenronde voor dit contract, of None
    als er (nog) geen verzoek tot tekenen is verstuurd."""
    pad = _ronde_pad(pand_slug, bestandsnaam, state_dir)
    if not pad.is_file():
        return None
    return json.loads(pad.read_text())


def _schrijf_ronde(pand_slug: str, bestandsnaam: str, state_dir: str, ronde: dict) -> None:
    pad = _ronde_pad(pand_slug, bestandsnaam, state_dir)
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text(json.dumps(ronde))


def bereken_betaalverzoek_bedrag(huurprijs: Decimal, borg: Decimal, ingangsdatum: date) -> Decimal:
    """Waarborgsom + de pro-rata huur vanaf de ingangsdatum t/m het einde van
    die kalendermaand (beide dagen meegerekend)."""
    dagen_in_maand = calendar.monthrange(ingangsdatum.year, ingangsdatum.month)[1]
    laatste_dag = date(ingangsdatum.year, ingangsdatum.month, dagen_in_maand)
    dagen_resterend = (laatste_dag - ingangsdatum).days + 1
    pro_rata_huur = (huurprijs * dagen_resterend / dagen_in_maand).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return borg + pro_rata_huur


def _nieuwe_ondertekenaar(id_: str, rol: str, naam: str, email: str) -> dict:
    return {
        "id": id_, "rol": rol, "naam": naam, "email": email, "token": secrets.token_urlsafe(32),
        "ondertekend_op": None, "ip_adres": None, "user_agent": None, "getekende_naam": None,
    }


def start_ondertekenronde(
    pand: Pand, pand_slug: str, bestandsnaam: str, metadata: dict,
    verhuurder_emails: list[str], state_dir: str = ".",
) -> dict:
    """Zet een nieuwe ondertekenronde op voor dit contract: de huurder, alle
    verhuurder(s) van het pand (gekoppeld op volgorde aan verhuurder_emails -
    dezelfde adressen als EMAIL_BCC + het pand-specifieke extra_bcc, zie
    webapp/app.py) en - als er een borgsteller met e-mailadres bekend is -
    ook de borgsteller, elk met een eigen unieke ondertekenlink.

    Idempotent: geeft de bestaande ronde terug als er al een loopt, zodat een
    dubbele klik geen nieuwe tokens/mails aanmaakt (wat de al verstuurde
    links zou laten samenvallen met een nieuwe, verwarrende ronde)."""
    bestaand = lees_ondertekenronde(pand_slug, bestandsnaam, state_dir)
    if bestaand is not None:
        return bestaand

    ondertekenaars = [
        _nieuwe_ondertekenaar("huurder", "huurder", metadata.get("huurder_naam", ""), metadata.get("email", "")),
    ]
    for i, (verhuurder, email) in enumerate(zip(pand.verhuurders, verhuurder_emails), start=1):
        ondertekenaars.append(_nieuwe_ondertekenaar(f"verhuurder-{i}", "verhuurder", verhuurder.naam, email))
    if metadata.get("borgsteller_naam") and metadata.get("borgsteller_email"):
        ondertekenaars.append(_nieuwe_ondertekenaar(
            "borgsteller", "borgsteller", metadata["borgsteller_naam"], metadata["borgsteller_email"]
        ))

    ronde = {
        "pand_slug": pand_slug, "bestandsnaam": bestandsnaam,
        "aangemaakt_op": datetime.now().isoformat(timespec="seconds"),
        "ondertekenaars": ondertekenaars, "afgerond_op": None, "getekend_bestandsnaam": None,
    }
    _schrijf_ronde(pand_slug, bestandsnaam, state_dir, ronde)

    index = _lees_index(state_dir)
    for ondertekenaar in ondertekenaars:
        index[ondertekenaar["token"]] = {"pand_slug": pand_slug, "bestandsnaam": bestandsnaam}
    _schrijf_index(state_dir, index)

    return ronde


def zoek_via_token(token: str, state_dir: str = ".") -> tuple[str, str, dict] | None:
    """Geeft (pand_slug, bestandsnaam, ondertekenaar) terug voor deze token,
    of None als de token onbekend is."""
    verwijzing = _lees_index(state_dir).get(token)
    if verwijzing is None:
        return None
    ronde = lees_ondertekenronde(verwijzing["pand_slug"], verwijzing["bestandsnaam"], state_dir)
    if ronde is None:
        return None
    for ondertekenaar in ronde["ondertekenaars"]:
        if ondertekenaar["token"] == token:
            return verwijzing["pand_slug"], verwijzing["bestandsnaam"], ondertekenaar
    return None


def markeer_ondertekend(
    pand_slug: str, bestandsnaam: str, ondertekenaar_id: str, state_dir: str,
    ip_adres: str, user_agent: str, getekende_naam: str,
) -> dict:
    """Legt de handtekening vast (tijdstip, IP, user-agent, getypte naam) en
    geeft de bijgewerkte ronde terug. Idempotent: is deze ondertekenaar al
    gemarkeerd als getekend, dan blijft de eerste registratie staan."""
    ronde = lees_ondertekenronde(pand_slug, bestandsnaam, state_dir)
    if ronde is None:
        raise ValueError(f"Geen ondertekenronde gevonden voor '{bestandsnaam}'.")
    for ondertekenaar in ronde["ondertekenaars"]:
        if ondertekenaar["id"] == ondertekenaar_id and ondertekenaar["ondertekend_op"] is None:
            ondertekenaar["ondertekend_op"] = datetime.now().isoformat(timespec="seconds")
            ondertekenaar["ip_adres"] = ip_adres
            ondertekenaar["user_agent"] = user_agent
            ondertekenaar["getekende_naam"] = getekende_naam
            break
    _schrijf_ronde(pand_slug, bestandsnaam, state_dir, ronde)
    return ronde


def alles_getekend(ronde: dict) -> bool:
    return all(o["ondertekend_op"] for o in ronde["ondertekenaars"])


def markeer_afgerond(pand_slug: str, bestandsnaam: str, state_dir: str, getekend_bestandsnaam: str) -> dict:
    ronde = lees_ondertekenronde(pand_slug, bestandsnaam, state_dir)
    ronde["afgerond_op"] = datetime.now().isoformat(timespec="seconds")
    ronde["getekend_bestandsnaam"] = getekend_bestandsnaam
    _schrijf_ronde(pand_slug, bestandsnaam, state_dir, ronde)
    return ronde


def bouw_handtekeningen_html(ronde: dict) -> str:
    """Het handtekeningenblok voor het definitieve, ondertekende contract:
    per ondertekenaar naam, rol, moment en IP-adres. Alle waarden komen
    (indirect) van publiek toegankelijke formuliervelden, dus expliciet
    ge-escaped - dit wordt rechtstreeks in de contract-HTML geplakt, niet via
    Jinja2 gerenderd."""
    rijen = []
    for o in ronde["ondertekenaars"]:
        rol_tekst = _ROLNAMEN_EN.get(o["rol"], o["rol"])
        naam = html.escape(o["getekende_naam"] or o["naam"])
        try:
            moment = datetime.fromisoformat(o["ondertekend_op"]).strftime("%d-%m-%Y %H:%M")
        except (TypeError, ValueError):
            moment = ""
        ip_adres = html.escape(o["ip_adres"] or "")
        rijen.append(
            "<tr><td>"
            f"<strong>{naam}</strong> ({rol_tekst})<br>"
            f"Electronically signed on {moment} - IP address {ip_adres}"
            "</td></tr>"
        )
    return '<table class="handtekeningen">' + "".join(rijen) + "</table>"


def bouw_betaal_en_tekenmail(pand: Pand, metadata: dict, teken_url: str, totaalbedrag: Decimal) -> dict[str, str]:
    """Mail naar de huurder: het betaalverzoek (borg + pro-rata huur) plus de
    link om het contract elektronisch te tekenen."""
    naam = metadata.get("huurder_naam") or "there"
    kamer = metadata.get("kamer", "")
    onderwerp = f"Signature & payment request - room {kamer}, {pand.naam}".strip()
    bedrag_tekst = f"{totaalbedrag:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    wie_nog = "the landlord(s)" + (" and guarantor" if metadata.get("borgsteller_naam") else "")
    tekst = (
        f"Dear {naam},\n\n"
        f"Thank you for confirming the draft rental agreement for room {kamer} at {pand.naam}. "
        f"Two things are needed to finalize it:\n\n"
        f"1) Payment of EUR {bedrag_tekst} (the security deposit plus the pro-rated rent for the "
        f"remainder of the starting month), to be paid to:\n"
        f"   IBAN: {pand.bunq_rekening_iban}\n"
        f"   Account holder: {pand.rekeninghouder_naam or pand.naam}\n\n"
        f"2) Signing the rental agreement electronically via this link:\n"
        f"   {teken_url}\n\n"
        f"Once the payment has been received and everyone has signed ({wie_nog} still need to sign "
        f"as well), we will send you the fully signed agreement, and your digital key (Bold) will be "
        f"activated - it becomes valid from the start date of your rental agreement.\n\n"
        f"Kind regards,\n{AFZENDER_NAAM}"
    )
    return {"onderwerp": onderwerp, "tekst": tekst}


def bouw_tekenmail_overig(rol: str, naam: str, pand: Pand, metadata: dict, teken_url: str) -> dict[str, str]:
    """Mail naar de verhuurder(s) of de borgsteller: verzoek om het contract
    elektronisch te tekenen."""
    kamer = metadata.get("kamer", "")
    huurder_naam = metadata.get("huurder_naam", "")
    onderwerp = f"Signature request - room {kamer}, {pand.naam}".strip()
    rol_tekst = _ROLNAMEN_EN.get(rol, rol)
    tekst = (
        f"Dear {naam},\n\n"
        f"Please sign the rental agreement for room {kamer} at {pand.naam} (tenant: {huurder_naam}) "
        f"in your role as {rol_tekst}, via this link:\n\n"
        f"{teken_url}\n\n"
        f"Kind regards,\n{AFZENDER_NAAM}"
    )
    return {"onderwerp": onderwerp, "tekst": tekst}


def bouw_getekend_contract_mail(pand: Pand, metadata: dict) -> dict[str, str]:
    """Mail met het volledig ondertekende contract als bijlage, verstuurd
    naar alle partijen zodra iedereen getekend heeft."""
    naam = metadata.get("huurder_naam") or "there"
    kamer = metadata.get("kamer", "")
    onderwerp = f"Signed rental agreement - room {kamer}, {pand.naam}".strip()
    tekst = (
        f"Dear {naam},\n\n"
        f"Please find attached the fully signed rental agreement for room {kamer} at {pand.naam} - "
        f"all parties have now signed.\n\n"
        f"You will need this document to register (inschrijven) at this address with the municipality "
        f"(gemeente).\n\n"
        f"Kind regards,\n{AFZENDER_NAAM}"
    )
    return {"onderwerp": onderwerp, "tekst": tekst}

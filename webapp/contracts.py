"""Genereert een concept-huurcontract (HTML, met een echte PDF-export via
xhtml2pdf) op basis van het sjabloon in contract_templates/. Elk pand heeft
zijn eigen submap onder gegenereerde_contracten/.

Het sjabloon (basistekst + artikelen, geldt voor alle panden) is via de site
zelf aan te passen ("Contractsjabloon aanpassen", zie lees_sjabloon()/
schrijf_sjabloon() hieronder) - de aangepaste versie wordt in STATE_DIR
opgeslagen (overleeft dus een herbuild/redeploy) en overschrijft dan de
meegeleverde standaardtekst uit contract_templates/.

BELANGRIJK: het meegeleverde sjabloon is gebaseerd op een echt gebruikt
huurcontract, maar is geen juridisch gecontroleerde huurovereenkomst op zich.
Laat de inhoud van contract_templates/huurovereenkomst_voorbeeld.html
controleren (bijv. door een jurist of tegen de Rijksoverheid-
modelhuurovereenkomst) voordat je een gegenereerd contract laat ondertekenen.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError, select_autoescape
from werkzeug.datastructures import ImmutableMultiDict
from xhtml2pdf import pisa

from kamerverhuur_scanner.models import Pand

from .reminders import AFZENDER_NAAM

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "contract_templates"
BASIS_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "gegenereerde_contracten"
STANDAARD_SJABLOON_NAAM = "huurovereenkomst_voorbeeld.html"

_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=select_autoescape())

# Namen van de variabelen die in het sjabloon gebruikt kunnen worden (zie
# _bouw_context() hieronder) - getoond op het "Contractsjabloon aanpassen"-
# scherm zodat een beheerder weet welke velden beschikbaar zijn.
SJABLOON_VARIABELEN = [
    "pand", "kamer", "kamer_omschrijving", "huurder_naam", "geboortedatum",
    "geboorteplaats", "studentnummer", "studierichting", "borgsteller_naam",
    "borgsteller_relatie", "kale_huurprijs", "servicekosten", "huurprijs",
    "borg", "aantal_bewoners", "ingangsdatum", "einddatum", "bijzonderheden",
    "gegenereerd_op", "pdf_url",
]


class SjabloonFout(RuntimeError):
    """Het opgegeven sjabloon is geen geldige Jinja2-template (bv. een niet-
    gesloten {% if %} of een tikfout in een {{ variabele }})."""


def _sjabloon_override_pad(state_dir: str) -> Path:
    return Path(state_dir) / "contract_sjabloon.html"


def lees_standaard_sjabloon() -> str:
    """De meegeleverde standaardtekst (contract_templates/), ongeacht of er
    een aangepaste versie bestaat - gebruikt voor "Terugzetten naar
    standaard" en om op het bewerkscherm te vergelijken."""
    return (TEMPLATE_DIR / STANDAARD_SJABLOON_NAAM).read_text()


def lees_sjabloon(state_dir: str) -> str:
    """De tekst die daadwerkelijk gebruikt wordt om een contract te
    genereren: de aangepaste versie als die bestaat, anders de standaard."""
    override = _sjabloon_override_pad(state_dir)
    if override.is_file():
        return override.read_text()
    return lees_standaard_sjabloon()


def heeft_aangepast_sjabloon(state_dir: str) -> bool:
    return _sjabloon_override_pad(state_dir).is_file()


def schrijf_sjabloon(state_dir: str, inhoud: str) -> None:
    """Slaat een aangepast sjabloon op - valideert eerst of het geldige
    Jinja2-syntax is (ontbrekende {% endif %}'s e.d.), zodat een tikfout niet
    alle toekomstige contractgeneraties kapotmaakt."""
    try:
        _env.from_string(inhoud)
    except TemplateSyntaxError as exc:
        raise SjabloonFout(f"Ongeldige sjabloon-syntax: {exc}") from exc
    _sjabloon_override_pad(state_dir).write_text(inhoud)


def verwijder_sjabloon_override(state_dir: str) -> None:
    """Zet het sjabloon terug naar de meegeleverde standaardtekst."""
    _sjabloon_override_pad(state_dir).unlink(missing_ok=True)


def _slugify(tekst: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", tekst.lower()).strip("-") or "onbekend"


def _output_dir(pand_slug: str) -> Path:
    return BASIS_OUTPUT_DIR / _slugify(pand_slug)


def _datum_lang(iso_datum: str) -> str:
    """Zet een datum in "jjjj-mm-dd"-formaat (HTML date-input) om naar
    "dd-mm-jjjj". Geeft de invoer ongewijzigd terug als het formaat afwijkt
    (bv. al "onbepaalde tijd" of leeg)."""
    try:
        return datetime.strptime(iso_datum, "%Y-%m-%d").strftime("%d-%m-%Y")
    except ValueError:
        return iso_datum


def genereer_contract(pand_slug: str, pand: Pand, form: ImmutableMultiDict, state_dir: str = ".") -> str:
    output_dir = _output_dir(pand_slug)
    output_dir.mkdir(parents=True, exist_ok=True)
    context = _bouw_context(pand, form)

    slug = f"{_slugify(context['kamer'])}-{_slugify(context['huurder_naam'])}"
    bestandsnaam = f"{date.today():%Y-%m-%d}_{slug}.html"
    context["pdf_url"] = f"/pand/{pand_slug}/contracten/{bestandsnaam}/pdf"

    html = _env.from_string(lees_sjabloon(state_dir)).render(**context)
    (output_dir / bestandsnaam).write_text(html)
    _schrijf_metadata(output_dir, bestandsnaam, {
        "email": form.get("email", "").strip(),
        "huurder_naam": context["huurder_naam"],
        "kamer": context["kamer"],
        "borg": context["borg"],
    })
    return bestandsnaam


def _metadata_pad(output_dir: Path, bestandsnaam: str) -> Path:
    return output_dir / f"{bestandsnaam}.meta.json"


def _schrijf_metadata(output_dir: Path, bestandsnaam: str, metadata: dict) -> None:
    _metadata_pad(output_dir, bestandsnaam).write_text(json.dumps(metadata))


def lees_metadata(pand_slug: str, bestandsnaam: str) -> dict:
    """Gegevens die niet in de contracttekst zelf staan maar wel nodig zijn om
    het concept te kunnen mailen (bv. het e-mailadres van de huurder) - lege
    dict als er (nog) geen metadata-bestand is, bv. voor contracten die vóór
    deze functie bestond zijn gegenereerd."""
    veilige_naam = Path(bestandsnaam).name
    pad = _metadata_pad(_output_dir(pand_slug), veilige_naam)
    if not pad.is_file():
        return {}
    try:
        return json.loads(pad.read_text())
    except json.JSONDecodeError:
        return {}


def bouw_concept_email(pand: Pand, metadata: dict) -> dict[str, str]:
    """Stelt de (Engelstalige) e-mailtekst op waarmee het concept-huurcontract
    naar de kandidaat-huurder gemaild wordt - net als bouw_herinnering() in
    reminders.py kan de beheerder dit nog aanpassen op het voorbeeldscherm."""
    naam = metadata.get("huurder_naam") or "there"
    kamer = metadata.get("kamer", "")
    borg = metadata.get("borg", "")
    onderwerp = f"Draft rental agreement - room {kamer}, {pand.naam}".strip()
    borg_zin = f"the security deposit (EUR {borg})" if borg else "the security deposit"
    tekst = (
        f"Dear {naam},\n\n"
        f"Please find attached the draft rental agreement for room {kamer} at {pand.naam}.\n\n"
        f"Please take your time to review it, and let us know if you have any questions.\n\n"
        f"Once you confirm you are happy with the terms, we will send the agreement via DocHub "
        f"for final signature.\n\n"
        f"After that, the first payment is due: {borg_zin} plus the remaining (pro-rated) rent "
        f"for the first month. As soon as both the signed agreement and this payment have been "
        f"received, your digital key (Bold) will be activated - it becomes valid from the start "
        f"date of your rental agreement.\n\n"
        f"Kind regards,\n{AFZENDER_NAAM}"
    )
    return {"onderwerp": onderwerp, "tekst": tekst}


def _bouw_context(pand: Pand, form: ImmutableMultiDict) -> dict:
    kale = form.get("kale_huurprijs", "").strip()
    service = form.get("servicekosten", "").strip()
    try:
        aantal_bewoners = int(form.get("aantal_bewoners", "").strip() or "1")
    except ValueError:
        aantal_bewoners = 1
    return {
        "pand": pand,
        "kamer": form.get("kamer", "").strip(),
        "kamer_omschrijving": form.get("kamer_omschrijving", "").strip(),
        "huurder_naam": form.get("huurder_naam", "").strip(),
        "geboortedatum": _datum_lang(form.get("geboortedatum", "").strip()),
        "geboorteplaats": form.get("geboorteplaats", "").strip(),
        "studentnummer": form.get("studentnummer", "").strip(),
        "studierichting": form.get("studierichting", "").strip(),
        "borgsteller_naam": form.get("borgsteller_naam", "").strip(),
        "borgsteller_relatie": form.get("borgsteller_relatie", "").strip(),
        "kale_huurprijs": kale,
        "servicekosten": service,
        "huurprijs": form.get("huurprijs", "").strip(),
        "borg": form.get("borg", "").strip(),
        "aantal_bewoners": aantal_bewoners,
        "ingangsdatum": _datum_lang(form.get("ingangsdatum", "").strip()),
        "einddatum": _datum_lang(form.get("einddatum", "").strip()),
        "bijzonderheden": form.get("bijzonderheden", "").strip(),
        "gegenereerd_op": date.today().strftime("%d-%m-%Y"),
    }


def list_contracten(pand_slug: str) -> list[str]:
    output_dir = _output_dir(pand_slug)
    if not output_dir.exists():
        return []
    return sorted((p.name for p in output_dir.glob("*.html")), reverse=True)


def list_contracten_voor_kamer(pand_slug: str, kamer: str) -> list[str]:
    prefix = _slugify(kamer) + "-"
    resultaat = []
    for naam in list_contracten(pand_slug):
        _datum, _, rest = naam.partition("_")
        if rest.startswith(prefix):
            resultaat.append(naam)
    return resultaat


def lees_contract(pand_slug: str, bestandsnaam: str) -> str:
    veilige_naam = Path(bestandsnaam).name  # voorkomt path traversal (../)
    pad = _output_dir(pand_slug) / veilige_naam
    if pad.suffix != ".html" or not pad.is_file():
        raise FileNotFoundError(bestandsnaam)
    return pad.read_text()


def genereer_pdf(pand_slug: str, bestandsnaam: str) -> bytes:
    """Zet een eerder gegenereerd contract om naar PDF - handig om direct te
    kunnen uploaden naar DocHub voor de handtekeningaanvraag."""
    html = lees_contract(pand_slug, bestandsnaam)
    buffer = BytesIO()
    resultaat = pisa.CreatePDF(html, dest=buffer)
    if resultaat.err:
        raise PdfGenerationError(f"PDF-generatie mislukt voor '{bestandsnaam}' ({resultaat.err} fout(en)).")
    return buffer.getvalue()


class PdfGenerationError(RuntimeError):
    pass

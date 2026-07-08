"""Genereert een concept-huurcontract (HTML, met een echte PDF-export via
xhtml2pdf) op basis van het sjabloon in contract_templates/. Elk pand heeft
zijn eigen submap onder gegenereerde_contracten/.

BELANGRIJK: het meegeleverde sjabloon is gebaseerd op een echt gebruikt
huurcontract, maar is geen juridisch gecontroleerde huurovereenkomst op zich.
Laat de inhoud van contract_templates/huurovereenkomst_voorbeeld.html
controleren (bijv. door een jurist of tegen de Rijksoverheid-
modelhuurovereenkomst) voordat je een gegenereerd contract laat ondertekenen.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from werkzeug.datastructures import ImmutableMultiDict
from xhtml2pdf import pisa

from kamerverhuur_scanner.models import Pand

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "contract_templates"
BASIS_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "gegenereerde_contracten"

_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=select_autoescape())


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


def genereer_contract(pand_slug: str, pand: Pand, form: ImmutableMultiDict) -> str:
    output_dir = _output_dir(pand_slug)
    output_dir.mkdir(parents=True, exist_ok=True)
    context = _bouw_context(pand, form)

    slug = f"{_slugify(context['kamer'])}-{_slugify(context['huurder_naam'])}"
    bestandsnaam = f"{date.today():%Y-%m-%d}_{slug}.html"
    context["pdf_url"] = f"/pand/{pand_slug}/contracten/{bestandsnaam}/pdf"

    html = _env.get_template("huurovereenkomst_voorbeeld.html").render(**context)
    (output_dir / bestandsnaam).write_text(html)
    return bestandsnaam


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

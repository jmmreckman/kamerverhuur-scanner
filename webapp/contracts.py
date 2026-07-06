"""Genereert een concept-huurcontract (HTML, printbaar/op te slaan als PDF vanuit
de browser) op basis van het sjabloon in contract_templates/.

BELANGRIJK: het meegeleverde sjabloon bevat voorbeeld/placeholder-bepalingen,
geen juridisch gecontroleerde huurovereenkomst. Vervang de inhoud in
contract_templates/huurovereenkomst_voorbeeld.html door een gecontroleerd
modelcontract (bijv. de Rijksoverheid modelhuurovereenkomst) voordat je een
gegenereerd contract laat ondertekenen.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from werkzeug.datastructures import ImmutableMultiDict

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "contract_templates"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "gegenereerde_contracten"

_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=select_autoescape())


def _slugify(tekst: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", tekst.lower()).strip("-") or "onbekend"


def genereer_contract(form: ImmutableMultiDict) -> str:
    OUTPUT_DIR.mkdir(exist_ok=True)
    context = {
        "kamer": form.get("kamer", "").strip(),
        "huurder_naam": form.get("huurder_naam", "").strip(),
        "huurprijs": form.get("huurprijs", "").strip(),
        "borg": form.get("borg", "").strip(),
        "ingangsdatum": form.get("ingangsdatum", "").strip(),
        "bijzonderheden": form.get("bijzonderheden", "").strip(),
        "gegenereerd_op": date.today().strftime("%d-%m-%Y"),
    }
    html = _env.get_template("huurovereenkomst_voorbeeld.html").render(**context)

    slug = f"{_slugify(context['kamer'])}-{_slugify(context['huurder_naam'])}"
    bestandsnaam = f"{date.today():%Y-%m-%d}_{slug}.html"
    (OUTPUT_DIR / bestandsnaam).write_text(html)
    return bestandsnaam


def list_contracten() -> list[str]:
    if not OUTPUT_DIR.exists():
        return []
    return sorted((p.name for p in OUTPUT_DIR.glob("*.html")), reverse=True)


def list_contracten_voor_kamer(kamer: str) -> list[str]:
    prefix = _slugify(kamer) + "-"
    resultaat = []
    for naam in list_contracten():
        _datum, _, rest = naam.partition("_")
        if rest.startswith(prefix):
            resultaat.append(naam)
    return resultaat


def lees_contract(bestandsnaam: str) -> str:
    veilige_naam = Path(bestandsnaam).name  # voorkomt path traversal (../)
    pad = OUTPUT_DIR / veilige_naam
    if pad.suffix != ".html" or not pad.is_file():
        raise FileNotFoundError(bestandsnaam)
    return pad.read_text()

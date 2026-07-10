"""Genereert een concept-huurcontract (HTML, met een echte PDF-export via
xhtml2pdf) op basis van het sjabloon in contract_templates/. Elk pand heeft
zijn eigen submap onder gegenereerde_contracten/, die - net als de aangepaste
sjabloontekst - onder STATE_DIR staat (dus /app/data in productie, gekoppeld
aan een volume in docker-compose.yml) zodat gegenereerde contracten een
herbuild/redeploy overleven in plaats van te verdwijnen zodra de container
opnieuw wordt opgebouwd.

De artikelen (het middenstuk van het contract, tussen de ARTIKELEN:START/
ARTIKELEN:EINDE-markeringen in contract_templates/) zijn via de site zelf aan
te passen ("Contractsjabloon aanpassen", zie lees_artikelen()/
schrijf_artikelen() hieronder) in een simpel tekstverwerker-scherm (geen HTML/
CSS-code te zien) - de aangepaste versie wordt in STATE_DIR opgeslagen
(overleeft dus een herbuild/redeploy) en overschrijft dan de meegeleverde
standaardartikelen. De vaste opmaak eromheen (CSS, kop met partijengegevens,
handtekeningenblok) blijft ongewijzigd en is niet via de site te bewerken -
het handtekeningenblok (tussen HANDTEKENINGEN:START/EINDE) wordt door
webapp/ondertekenen.py automatisch ingevuld zodra een contract elektronisch
volledig ondertekend is (zie genereer_getekend_contract() hieronder).

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


_ARTIKELEN_START = "<!-- ARTIKELEN:START -->"
_ARTIKELEN_EINDE = "<!-- ARTIKELEN:EINDE -->"

_HANDTEKENINGEN_START = "<!-- HANDTEKENINGEN:START -->"
_HANDTEKENINGEN_EINDE = "<!-- HANDTEKENINGEN:EINDE -->"

# Achtervoegsel van de bestandsnaam van een volledig ondertekend contract
# (zie genereer_getekend_contract() en webapp/ondertekenen.py) - zo is op de
# Contracten-pagina in één oogopslag te zien of het om het concept of de
# definitieve, ondertekende versie gaat.
GETEKEND_ACHTERVOEGSEL = "-getekend"


class SjabloonFout(RuntimeError):
    """Het opgegeven sjabloon is geen geldige Jinja2-template (bv. een niet-
    gesloten {% if %} of een tikfout in een {{ variabele }})."""


def _sjabloon_override_pad(state_dir: str) -> Path:
    return Path(state_dir) / "contract_sjabloon.html"


def lees_standaard_sjabloon() -> str:
    """De volledige meegeleverde standaardtekst (contract_templates/),
    inclusief de vaste opmaak (CSS, partijentabel, handtekeningenblok) - dit
    is wat er daadwerkelijk gerenderd wordt, niet wat een beheerder op het
    bewerkscherm te zien krijgt (zie lees_standaard_artikelen())."""
    return (TEMPLATE_DIR / STANDAARD_SJABLOON_NAAM).read_text()


def _split_sjabloon(html: str) -> tuple[str, str, str]:
    """Splitst de volledige sjabloontekst in (vaste kop-/partijen-HTML, de
    bewerkbare artikelen, vaste handtekeningen-HTML) aan de hand van de
    ARTIKELEN:START/EINDE-markeringen in het standaardsjabloon."""
    voor, _, rest = html.partition(_ARTIKELEN_START)
    artikelen, _, na = rest.partition(_ARTIKELEN_EINDE)
    return voor, artikelen.strip("\n"), na


def lees_standaard_artikelen() -> str:
    """Alleen de bewerkbare artikelen (Artikel 1 t/m de aanvullende
    afspraken) uit de meegeleverde standaardtekst - dit is wat een beheerder
    ziet en bewerkt op het "Contractsjabloon aanpassen"-scherm."""
    _voor, artikelen, _na = _split_sjabloon(lees_standaard_sjabloon())
    return artikelen


def lees_artikelen(state_dir: str) -> str:
    """De artikelen die daadwerkelijk gebruikt worden om een contract te
    genereren: de aangepaste versie als die bestaat, anders de standaard.
    Een override die (nog) een heel document is - van vóór dit scherm een
    tekstverwerker-editor voor alleen de artikelen werd - wordt genegeerd,
    zodat die niet dubbel in de opmaak terechtkomt."""
    override = _sjabloon_override_pad(state_dir)
    if override.is_file():
        inhoud = override.read_text()
        if "<!doctype" not in inhoud.lower():
            return inhoud
    return lees_standaard_artikelen()


def heeft_aangepast_sjabloon(state_dir: str) -> bool:
    return _sjabloon_override_pad(state_dir).is_file()


def schrijf_artikelen(state_dir: str, artikelen_html: str) -> None:
    """Slaat aangepaste artikelen op - valideert eerst (samen met de vaste
    opmaak eromheen) of het geldige Jinja2-syntax is (ontbrekende
    {% endif %}'s e.d.), zodat een tikfout niet alle toekomstige
    contractgeneraties kapotmaakt."""
    voor, _standaard_artikelen, na = _split_sjabloon(lees_standaard_sjabloon())
    try:
        _env.from_string(voor + artikelen_html + na)
    except TemplateSyntaxError as exc:
        raise SjabloonFout(f"Ongeldige sjabloon-syntax: {exc}") from exc
    _sjabloon_override_pad(state_dir).write_text(artikelen_html)


def verwijder_sjabloon_override(state_dir: str) -> None:
    """Zet de artikelen terug naar de meegeleverde standaardtekst."""
    _sjabloon_override_pad(state_dir).unlink(missing_ok=True)


def lees_sjabloon(state_dir: str) -> str:
    """De volledige sjabloontekst (vaste opmaak + de - eventueel aangepaste -
    artikelen) waarmee een contract daadwerkelijk gerenderd wordt."""
    voor, _standaard_artikelen, na = _split_sjabloon(lees_standaard_sjabloon())
    return voor + lees_artikelen(state_dir) + na


def _slugify(tekst: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", tekst.lower()).strip("-") or "onbekend"


def _output_dir(pand_slug: str, state_dir: str) -> Path:
    return Path(state_dir) / "gegenereerde_contracten" / _slugify(pand_slug)


def output_dir(pand_slug: str, state_dir: str) -> Path:
    """Publieke variant van _output_dir() - gebruikt door webapp/ondertekenen.py
    om de ondertekenronde-JSON in dezelfde map als het contract zelf te
    bewaren."""
    return _output_dir(pand_slug, state_dir)


def _datum_lang(iso_datum: str) -> str:
    """Zet een datum in "jjjj-mm-dd"-formaat (HTML date-input) om naar
    "dd-mm-jjjj". Geeft de invoer ongewijzigd terug als het formaat afwijkt
    (bv. al "onbepaalde tijd" of leeg)."""
    try:
        return datetime.strptime(iso_datum, "%Y-%m-%d").strftime("%d-%m-%Y")
    except ValueError:
        return iso_datum


def genereer_contract(pand_slug: str, pand: Pand, form: ImmutableMultiDict, state_dir: str = ".") -> str:
    output_dir = _output_dir(pand_slug, state_dir)
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
        "huurprijs": context["huurprijs"],
        # onderstaande velden staan hier alleen zodat een later "Verzoek tot
        # tekenen" (zie webapp/ondertekenen.py) de sheet nog kan bijwerken op
        # basis van dít contract, ook al is de generatie zelf allang voorbij -
        # zelfde velden/formaat als het huurcontract-formulier zelf.
        "kale_huurprijs": form.get("kale_huurprijs", "").strip(),
        "servicekosten": form.get("servicekosten", "").strip(),
        "ingangsdatum_iso": form.get("ingangsdatum", "").strip(),
        "einddatum_iso": form.get("einddatum", "").strip(),
        "geboortedatum": form.get("geboortedatum", "").strip(),
        "geboorteplaats": form.get("geboorteplaats", "").strip(),
        "studentnummer": form.get("studentnummer", "").strip(),
        "studierichting": form.get("studierichting", "").strip(),
        "borgsteller_naam": context["borgsteller_naam"],
        "borgsteller_relatie": form.get("borgsteller_relatie", "").strip(),
        "borgsteller_email": form.get("borgsteller_email", "").strip(),
    })
    return bestandsnaam


def _metadata_pad(output_dir: Path, bestandsnaam: str) -> Path:
    return output_dir / f"{bestandsnaam}.meta.json"


def _schrijf_metadata(output_dir: Path, bestandsnaam: str, metadata: dict) -> None:
    _metadata_pad(output_dir, bestandsnaam).write_text(json.dumps(metadata))


def lees_metadata(pand_slug: str, bestandsnaam: str, state_dir: str = ".") -> dict:
    """Gegevens die niet in de contracttekst zelf staan maar wel nodig zijn om
    het concept te kunnen mailen (bv. het e-mailadres van de huurder) - lege
    dict als er (nog) geen metadata-bestand is, bv. voor contracten die vóór
    deze functie bestond zijn gegenereerd."""
    veilige_naam = Path(bestandsnaam).name
    pad = _metadata_pad(_output_dir(pand_slug, state_dir), veilige_naam)
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
    onderwerp = f"Draft rental agreement - room {kamer}, {pand.naam}".strip()
    tekst = (
        f"Dear {naam},\n\n"
        f"Please find attached the draft rental agreement for room {kamer} at {pand.naam}.\n\n"
        f"Please take your time to review it, and let us know if you have any questions.\n\n"
        f"Once you confirm you are happy with the terms, we will send you a payment request and a "
        f"link to sign the agreement electronically. As soon as the payment and all signatures have "
        f"been received, your digital key (Bold) will be activated - it becomes valid from the start "
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


def list_contracten(pand_slug: str, state_dir: str = ".") -> list[str]:
    output_dir = _output_dir(pand_slug, state_dir)
    if not output_dir.exists():
        return []
    return sorted((p.name for p in output_dir.glob("*.html")), reverse=True)


def list_contracten_voor_kamer(pand_slug: str, kamer: str, state_dir: str = ".") -> list[str]:
    prefix = _slugify(kamer) + "-"
    resultaat = []
    for naam in list_contracten(pand_slug, state_dir):
        _datum, _, rest = naam.partition("_")
        if rest.startswith(prefix):
            resultaat.append(naam)
    return resultaat


def verwijder_contract(pand_slug: str, bestandsnaam: str, state_dir: str = ".") -> None:
    """Verwijdert een gegenereerd contract (en de bijbehorende metadata voor
    het mailscherm, als die er is) - bv. een proefcontract of een verkeerd
    ingevuld exemplaar dat niet meer relevant is. Doet niets als het bestand
    niet (meer) bestaat."""
    veilige_naam = Path(bestandsnaam).name  # voorkomt path traversal (../)
    if Path(veilige_naam).suffix != ".html":
        return
    output_dir = _output_dir(pand_slug, state_dir)
    (output_dir / veilige_naam).unlink(missing_ok=True)
    _metadata_pad(output_dir, veilige_naam).unlink(missing_ok=True)


def is_getekend_contract(bestandsnaam: str) -> bool:
    """Herkent aan de bestandsnaam of dit het volledig ondertekende contract
    is (i.p.v. het concept) - zie genereer_getekend_contract()."""
    return Path(bestandsnaam).stem.endswith(GETEKEND_ACHTERVOEGSEL)


def genereer_getekend_contract(pand_slug: str, bestandsnaam: str, handtekeningen_html: str, state_dir: str = ".") -> str:
    """Maakt van een (al volledig ondertekend) concept-contract de
    definitieve versie: neemt de eerder gegenereerde contracttekst en
    vervangt het lege handtekeningenblok door de echte ondertekeningen (naam,
    rol, moment, IP-adres - zie webapp/ondertekenen.py). Slaat op onder een
    naam die eindigt op "-getekend", zodat concept en definitief duidelijk te
    onderscheiden zijn op de Contracten-pagina."""
    html = lees_contract(pand_slug, bestandsnaam, state_dir)
    voor, _, rest = html.partition(_HANDTEKENINGEN_START)
    _oorspronkelijke_tabel, _, na = rest.partition(_HANDTEKENINGEN_EINDE)
    nieuwe_html = voor + handtekeningen_html + na

    getekend_bestandsnaam = f"{Path(bestandsnaam).stem}{GETEKEND_ACHTERVOEGSEL}.html"
    output_dir = _output_dir(pand_slug, state_dir)
    (output_dir / getekend_bestandsnaam).write_text(nieuwe_html)
    return getekend_bestandsnaam


def lees_contract(pand_slug: str, bestandsnaam: str, state_dir: str = ".") -> str:
    veilige_naam = Path(bestandsnaam).name  # voorkomt path traversal (../)
    pad = _output_dir(pand_slug, state_dir) / veilige_naam
    if pad.suffix != ".html" or not pad.is_file():
        raise FileNotFoundError(bestandsnaam)
    return pad.read_text()


def genereer_pdf(pand_slug: str, bestandsnaam: str, state_dir: str = ".") -> bytes:
    """Zet een eerder gegenereerd contract om naar PDF - handig om direct te
    kunnen uploaden naar DocHub voor de handtekeningaanvraag."""
    html = lees_contract(pand_slug, bestandsnaam, state_dir)
    buffer = BytesIO()
    resultaat = pisa.CreatePDF(html, dest=buffer)
    if resultaat.err:
        raise PdfGenerationError(f"PDF-generatie mislukt voor '{bestandsnaam}' ({resultaat.err} fout(en)).")
    return buffer.getvalue()


class PdfGenerationError(RuntimeError):
    pass

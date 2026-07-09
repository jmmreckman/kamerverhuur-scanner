from __future__ import annotations

from datetime import date
from html import escape
from urllib.parse import quote

from .pipeline import RunResult
from .state import ListingState

_STYLE = """
body { font-family: Arial, Helvetica, sans-serif; color: #1a1a1a; }
h1 { font-size: 20px; }
h2 { font-size: 16px; margin-top: 28px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }
table { border-collapse: collapse; width: 100%; margin-top: 8px; table-layout: fixed; }
th, td {
  text-align: left; padding: 6px 10px; border-bottom: 1px solid #eee; font-size: 14px;
  vertical-align: top; word-break: break-word; overflow-wrap: anywhere;
}
th { background: #f4f4f4; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; }
.badge-nieuw { background: #d7f0d7; color: #1a5c1a; }
.badge-check { background: #fff3cd; color: #7a5c00; }
.small { color: #666; font-size: 12px; }
.actie { display: inline-block; white-space: nowrap; }
.actie-verwijder { color: #a12b2b; }
"""

# Sommige e-mailclients (o.a. Gmail-mobiel) negeren <style>-blokken deels of geheel, dus
# de meest kwetsbare cel (lange, aaneengesloten monumentenregister-URL's zonder
# afbreekpunten) krijgt de word-break/max-width ook als inline style -- dat voorkomt dat
# die ene kolom de rest van de tabel scheeftrekt, ook als de <style> genegeerd wordt.
_OPSLAG_TD_STYLE = "word-break: break-word; overflow-wrap: anywhere; max-width: 260px;"

_VERWIJDER_BODY = (
    "Automatisch gegenereerd -- niet aanpassen. Verstuur deze mail om dit huis uit "
    "de lijst te halen."
)


def _dagen_bekend(item: ListingState, today: date) -> int:
    eerst = date.fromisoformat(item.eerst_gezien)
    return (today - eerst).days


def _euro(bedrag: int | float | None) -> str:
    if bedrag is None:
        return "-"
    return f"€{bedrag:,.0f}".replace(",", ".")


def _verwijder_mailto(scanner_email: str, object_id: str) -> str:
    subject = quote(f"Verwijder {object_id}")
    body = quote(_VERWIJDER_BODY)
    return f"mailto:{scanner_email}?subject={subject}&body={body}"


def _acties_html(item: ListingState, scanner_email: str) -> str:
    verwijder_url = _verwijder_mailto(scanner_email, item.object_id)
    return (
        f'<span class="actie"><a href="{escape(item.url)}">Bekijk advertentie &rarr;</a></span><br>'
        f'<span class="actie actie-verwijder"><a href="{escape(verwijder_url)}">Verwijderen</a></span>'
    )


def _row(item: ListingState, today: date, scanner_email: str) -> str:
    dagen = _dagen_bekend(item, today)
    is_nieuw = dagen == 0
    badges = []
    if is_nieuw:
        badges.append('<span class="badge badge-nieuw">nieuw vandaag</span>')
    if item.woz_check_nodig:
        badges.append('<span class="badge badge-check">check WOZ-waarde</span>')

    opmerking_html = f'<br><span class="small">{escape(item.opmerking)}</span>' if item.opmerking else ""
    oppervlakte_tekst = f"{item.bag_oppervlakte} m² (BAG)" if item.bag_oppervlakte else "onbekend"
    prijs_per_m2_tekst = _euro(item.prijs_per_m2) + "/m²" if item.prijs_per_m2 else "-"
    opslag_html = (
        "<br>".join(f'<span class="small">{escape(s)}</span>' for s in item.huurprijsopslag_signalen)
        or '<span class="small">geen gevonden</span>'
    )

    return f"""
    <tr>
      <td>{escape(item.weergavenaam)}</td>
      <td>{escape(item.wijknaam or '-')}</td>
      <td>{_euro(item.prijs)}</td>
      <td>{oppervlakte_tekst}</td>
      <td>{prijs_per_m2_tekst}</td>
      <td>{dagen} dag{'en' if dagen != 1 else ''}</td>
      <td>{' '.join(badges)}{opmerking_html}</td>
      <td style="{_OPSLAG_TD_STYLE}">{opslag_html}</td>
      <td>{_acties_html(item, scanner_email)}</td>
    </tr>
    """


_ACTIEF_TABEL_HEADER = """
    <tr>
      <th style="width:16%">Adres</th><th style="width:9%">Wijk</th>
      <th style="width:8%">Vraagprijs</th><th style="width:9%">Oppervlakte</th>
      <th style="width:7%">€/m²</th><th style="width:8%">Dagen bekend</th>
      <th style="width:12%">Nog te checken</th><th style="width:20%">Mogelijke huurprijsopslag</th>
      <th style="width:11%">Acties</th>
    </tr>
"""


def _afvallen_row(item: ListingState) -> str:
    return f"""
    <tr>
      <td><a href="{escape(item.url)}">{escape(item.weergavenaam)}</a></td>
      <td>{escape(item.afvalreden or '-')}</td>
    </tr>
    """


def build_html_report(result: RunResult, today: date, scanner_email: str, expiry_days: int = 30) -> str:
    nieuw_actief_ids = {item.object_id for item in result.nieuw_actief}
    nieuwe_kansen_rows = "".join(
        _row(item, today, scanner_email) for item in result.alle_actief if item.object_id in nieuw_actief_ids
    )
    actieve_rows = "".join(_row(item, today, scanner_email) for item in result.alle_actief)
    nieuw_afgevallen_rows = "".join(_afvallen_row(item) for item in result.nieuw_afgevallen)
    handmatig_verwijderd_rows = "".join(_afvallen_row(item) for item in result.handmatig_verwijderd)
    onbekend_rows = "".join(_afvallen_row(item) for item in result.nieuw_onbekend_adres)

    fouten_html = ""
    if result.fouten:
        items = "".join(f"<li>{escape(f)}</li>" for f in result.fouten)
        fouten_html = f"<h2>Let op: fouten tijdens dit run</h2><ul>{items}</ul>"

    return f"""<!doctype html>
<html lang="nl">
<head><meta charset="utf-8"><style>{_STYLE}</style></head>
<body>
  <h1>Kamerverhuur-scanner Rotterdam — {today.strftime('%d-%m-%Y')}</h1>
  <p class="small">
    {len(nieuw_actief_ids)} nieuwe kandidaten vandaag, {len(result.alle_actief)} in totaal nog open,
    {len(result.nieuw_afgevallen)} vandaag afgevallen op de geo-checks.
  </p>

  <h2>Nieuwe kansen vandaag ({len(nieuw_actief_ids)})</h2>
  <table>
    {_ACTIEF_TABEL_HEADER}
    {nieuwe_kansen_rows or '<tr><td colspan="9">Geen nieuwe kansen vandaag.</td></tr>'}
  </table>

  <h2>Openstaande kansen ({len(result.alle_actief)})</h2>
  <p class="small">
    Deze huizen zijn NIET afgevallen op nul-quotumgebied, de 50-meter kamerverhuurvergunning-check of
    (waar van toepassing) de automatische WOZ-check voor opkoopbescherming. Gesorteerd op vraagprijs
    per m² (laagste eerst), op basis van de officiële BAG-oppervlakte — die wijkt soms af van wat in de
    advertentietekst staat. "Dagen bekend" = dagen sinds dit systeem het huis voor het eerst zag in je
    Funda-alertmail. Een huis verdwijnt vanzelf na {expiry_days} dagen als het niet eerder handmatig
    verwijderd is — er wordt niet automatisch op "verkocht" of "onder bod" gecheckt, dat zie je zelf
    aan hoe lang een huis al op de lijst staat.
    Klik "Verwijderen" om een huis er zelf direct uit te halen (bijv. als het toch niet voldoet).
  </p>
  <table>
    {_ACTIEF_TABEL_HEADER}
    {actieve_rows or '<tr><td colspan="9">Geen openstaande kansen.</td></tr>'}
  </table>

  <h2>Handmatig verwijderd ({len(result.handmatig_verwijderd)})</h2>
  <table>
    <tr><th>Adres</th><th>Reden</th></tr>
    {handmatig_verwijderd_rows or '<tr><td colspan="2">Geen.</td></tr>'}
  </table>

  <h2>Vandaag afgevallen op geo-checks ({len(result.nieuw_afgevallen)})</h2>
  <table>
    <tr><th>Adres</th><th>Reden</th></tr>
    {nieuw_afgevallen_rows or '<tr><td colspan="2">Geen.</td></tr>'}
  </table>

  <h2>Kon niet automatisch verwerkt worden ({len(result.nieuw_onbekend_adres)})</h2>
  <p class="small">Bekijk deze zelf even handmatig op funda — het adres kon niet automatisch herleid worden.</p>
  <table>
    <tr><th>Link</th><th>Reden</th></tr>
    {onbekend_rows or '<tr><td colspan="2">Geen.</td></tr>'}
  </table>

  {fouten_html}

  <p class="small" style="margin-top:32px;">
    Herinnering: de WOZ-waarde wordt normaal automatisch opgehaald (via de WOZ-API) en huizen
    boven de opkoopbeschermingsgrens vallen dan al niet meer af — de badge "check WOZ-waarde"
    verschijnt alleen als dat een keer niet is gelukt (zie eventuele opmerking bij het huis).
    Vraagprijs komt uit de opmaak van je Funda-mail zelf en is daardoor iets kwetsbaarder dan de
    rest — klopt een prijs een keer niet, meld dat dan even. "Verwijderen" opent een kant-en-klare
    e-mail; gewoon versturen (niet aanpassen) en het huis is er de volgende run uit.
  </p>
  <p class="small">
    "Mogelijke huurprijsopslag" checkt automatisch op rijksmonument en rijksbeschermd
    stads-/dorpsgezicht (officiële Rijksdienst-data) en nieuwbouwopslag (BAG-bouwjaar) — deze zijn
    betrouwbaar maar altijd met "mogelijk" gemarkeerd omdat de exacte toepassing van de opslag
    (bijv. niet ook al een andere monumentenopslag) je zelf moet checken. Gemeentelijk monument wordt
    ook gecheckt, maar op basis van een door een derde gepubliceerde lijst uit 2021 — dus minder
    zeker, altijd verifiëren op monumentenregister.rotterdam.nl. Provinciaal monument (ook 15%) wordt
    niet automatisch gecheckt (geen bevraagbare open data beschikbaar, en komt in Rotterdam vrijwel
    nooit voor) — check dit zelf als het voor jouw pand relevant lijkt. "geen gevonden" betekent dus
    niet dat er zeker geen opslag mogelijk is, alleen dat de automatische checks niets vonden.
  </p>
</body>
</html>
"""


def _item_regels(item: ListingState, today: date, scanner_email: str) -> list[str]:
    dagen = _dagen_bekend(item, today)
    extra = []
    if item.woz_check_nodig:
        extra.append("check WOZ-waarde")
    oppervlakte_tekst = f"{item.bag_oppervlakte} m² (BAG)" if item.bag_oppervlakte else "oppervlakte onbekend"
    prijs_per_m2_tekst = f"{_euro(item.prijs_per_m2)}/m²" if item.prijs_per_m2 else "€/m² onbekend"
    regels = [
        f"- {item.weergavenaam} ({item.wijknaam or '-'}, {dagen} dagen bekend)",
        f"    bekijk: {item.url}",
        f"    verwijderen: {_verwijder_mailto(scanner_email, item.object_id)}",
        f"    {_euro(item.prijs)}, {oppervlakte_tekst}, {prijs_per_m2_tekst}",
    ]
    if extra:
        regels.append(f"    nog te checken: {', '.join(extra)}")
    if item.huurprijsopslag_signalen:
        regels.append("    mogelijke huurprijsopslag:")
        for signaal in item.huurprijsopslag_signalen:
            regels.append(f"      - {signaal}")
    if item.opmerking:
        regels.append(f"    let op: {item.opmerking}")
    return regels


def build_text_report(result: RunResult, today: date, scanner_email: str) -> str:
    nieuw_actief_ids = {item.object_id for item in result.nieuw_actief}
    lines = [f"Kamerverhuur-scanner Rotterdam — {today.strftime('%d-%m-%Y')}", ""]

    lines.append(f"Nieuwe kansen vandaag ({len(nieuw_actief_ids)}):")
    nieuwe_kansen = [item for item in result.alle_actief if item.object_id in nieuw_actief_ids]
    for item in nieuwe_kansen:
        lines.extend(_item_regels(item, today, scanner_email))
    if not nieuwe_kansen:
        lines.append("  (geen)")

    lines.append("")
    lines.append(f"Openstaande kansen ({len(result.alle_actief)}), gesorteerd op €/m²:")
    for item in result.alle_actief:
        lines.extend(_item_regels(item, today, scanner_email))
    if not result.alle_actief:
        lines.append("  (geen)")

    lines.append("")
    lines.append(f"Handmatig verwijderd ({len(result.handmatig_verwijderd)}):")
    for item in result.handmatig_verwijderd:
        lines.append(f"- {item.weergavenaam}: {item.afvalreden} ({item.url})")
    if not result.handmatig_verwijderd:
        lines.append("  (geen)")

    lines.append("")
    lines.append(f"Vandaag afgevallen op geo-checks ({len(result.nieuw_afgevallen)}):")
    for item in result.nieuw_afgevallen:
        lines.append(f"- {item.weergavenaam}: {item.afvalreden} ({item.url})")
    if not result.nieuw_afgevallen:
        lines.append("  (geen)")

    if result.nieuw_onbekend_adres:
        lines.append("")
        lines.append(f"Kon niet automatisch verwerkt worden ({len(result.nieuw_onbekend_adres)}):")
        for item in result.nieuw_onbekend_adres:
            lines.append(f"- {item.url}: {item.afvalreden}")

    if result.fouten:
        lines.append("")
        lines.append("Fouten tijdens dit run:")
        for fout in result.fouten:
            lines.append(f"- {fout}")

    return "\n".join(lines)

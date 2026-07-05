from __future__ import annotations

from datetime import date
from html import escape

from .pipeline import RunResult
from .state import ListingState

_STYLE = """
body { font-family: Arial, Helvetica, sans-serif; color: #1a1a1a; }
h1 { font-size: 20px; }
h2 { font-size: 16px; margin-top: 28px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }
table { border-collapse: collapse; width: 100%; margin-top: 8px; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #eee; font-size: 14px; vertical-align: top; }
th { background: #f4f4f4; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; }
.badge-nieuw { background: #d7f0d7; color: #1a5c1a; }
.badge-check { background: #fff3cd; color: #7a5c00; }
.small { color: #666; font-size: 12px; }
"""


def _dagen_bekend(item: ListingState, today: date) -> int:
    eerst = date.fromisoformat(item.eerst_gezien)
    return (today - eerst).days


def _euro(bedrag: int | float | None) -> str:
    if bedrag is None:
        return "-"
    return f"€{bedrag:,.0f}".replace(",", ".")


def _row(item: ListingState, today: date) -> str:
    dagen = _dagen_bekend(item, today)
    is_nieuw = dagen == 0
    badges = []
    if is_nieuw:
        badges.append('<span class="badge badge-nieuw">nieuw vandaag</span>')
    if item.woz_check_nodig:
        badges.append('<span class="badge badge-check">check WOZ-waarde</span>')
    if is_nieuw:
        badges.append('<span class="badge badge-check">markeer favoriet op funda</span>')
    badges.append('<span class="badge badge-check">check zelfbewoningsplicht</span>')

    opmerking_html = f'<br><span class="small">{escape(item.opmerking)}</span>' if item.opmerking else ""
    oppervlakte_tekst = f"{item.bag_oppervlakte} m² (BAG)" if item.bag_oppervlakte else "onbekend"
    prijs_per_m2_tekst = _euro(item.prijs_per_m2) + "/m²" if item.prijs_per_m2 else "-"

    return f"""
    <tr>
      <td><a href="{escape(item.url)}">{escape(item.weergavenaam)}</a></td>
      <td>{escape(item.wijknaam or '-')}</td>
      <td>{_euro(item.prijs)}</td>
      <td>{oppervlakte_tekst}</td>
      <td>{prijs_per_m2_tekst}</td>
      <td>{dagen} dag{'en' if dagen != 1 else ''}</td>
      <td>{' '.join(badges)}{opmerking_html}</td>
    </tr>
    """


def _afvallen_row(item: ListingState) -> str:
    return f"""
    <tr>
      <td><a href="{escape(item.url)}">{escape(item.weergavenaam)}</a></td>
      <td>{escape(item.afvalreden or '-')}</td>
    </tr>
    """


def build_html_report(result: RunResult, today: date) -> str:
    nieuw_actief_ids = {item.object_id for item in result.nieuw_actief}
    actieve_rows = "".join(_row(item, today) for item in result.alle_actief)
    nieuw_afgevallen_rows = "".join(_afvallen_row(item) for item in result.nieuw_afgevallen)
    niet_meer_te_koop_rows = "".join(_afvallen_row(item) for item in result.niet_meer_te_koop)
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
    {len(result.nieuw_afgevallen)} vandaag afgevallen op de geo-checks,
    {len(result.niet_meer_te_koop)} niet meer te koop.
  </p>

  <h2>Openstaande kansen ({len(result.alle_actief)})</h2>
  <p class="small">
    Deze huizen zijn NIET afgevallen op nul-quotumgebied, de 50-meter kamerverhuurvergunning-check of
    (waar van toepassing) de automatische WOZ-check voor opkoopbescherming. Gesorteerd op vraagprijs
    per m² (laagste eerst), op basis van de officiële BAG-oppervlakte — die wijkt soms af van wat in de
    advertentietekst staat. "Dagen bekend" = dagen sinds dit systeem het huis voor het eerst zag in je
    Funda-alertmail. Markeer nieuwe huizen als favoriet op funda.nl zodat "niet meer te koop"
    automatisch gedetecteerd kan worden (zie hieronder) — dat is de enige nog benodigde klik.
    Alleen "check zelfbewoningsplicht" blijft een korte handmatige leesstap.
  </p>
  <table>
    <tr>
      <th>Adres</th><th>Wijk</th><th>Vraagprijs</th><th>Oppervlakte</th><th>€/m²</th>
      <th>Dagen bekend</th><th>Nog te checken</th>
    </tr>
    {actieve_rows or '<tr><td colspan="7">Geen openstaande kansen.</td></tr>'}
  </table>

  <h2>Niet meer te koop ({len(result.niet_meer_te_koop)})</h2>
  <p class="small">
    Op basis van je Funda-favorieten-e-mail (onder bod / verkocht / in onderhandeling) automatisch
    uit "Openstaande kansen" gehaald. Dit werkt alleen voor huizen die je zelf als favoriet had
    gemarkeerd op funda.nl.
  </p>
  <table>
    <tr><th>Adres</th><th>Reden</th></tr>
    {niet_meer_te_koop_rows or '<tr><td colspan="2">Geen.</td></tr>'}
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
    "check zelfbewoningsplicht" staat er altijd bij: dit kan niet automatisch, funda blokkeert
    geautomatiseerd bezoek aan advertentiepagina's, dus lees de tekst zelf even door op dat woord.
    Vraagprijs en "niet meer te koop"-status komen uit de opmaak van je Funda-mails zelf en zijn
    daardoor iets kwetsbaarder dan de rest — klopt een prijs een keer niet, meld dat dan even.
  </p>
</body>
</html>
"""


def build_text_report(result: RunResult, today: date) -> str:
    lines = [f"Kamerverhuur-scanner Rotterdam — {today.strftime('%d-%m-%Y')}", ""]
    lines.append(f"Openstaande kansen ({len(result.alle_actief)}), gesorteerd op €/m²:")
    for item in result.alle_actief:
        dagen = _dagen_bekend(item, today)
        extra = []
        if item.woz_check_nodig:
            extra.append("check WOZ-waarde")
        if dagen == 0:
            extra.append("markeer favoriet op funda")
        extra.append("check zelfbewoningsplicht")
        oppervlakte_tekst = f"{item.bag_oppervlakte} m² (BAG)" if item.bag_oppervlakte else "oppervlakte onbekend"
        prijs_per_m2_tekst = f"{_euro(item.prijs_per_m2)}/m²" if item.prijs_per_m2 else "€/m² onbekend"
        lines.append(f"- {item.weergavenaam} ({item.wijknaam or '-'}, {dagen} dagen bekend) {item.url}")
        lines.append(f"    {_euro(item.prijs)}, {oppervlakte_tekst}, {prijs_per_m2_tekst}")
        lines.append(f"    nog te checken: {', '.join(extra)}")
        if item.opmerking:
            lines.append(f"    let op: {item.opmerking}")
    if not result.alle_actief:
        lines.append("  (geen)")

    lines.append("")
    lines.append(f"Niet meer te koop ({len(result.niet_meer_te_koop)}):")
    for item in result.niet_meer_te_koop:
        lines.append(f"- {item.weergavenaam}: {item.afvalreden} ({item.url})")
    if not result.niet_meer_te_koop:
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

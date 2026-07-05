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


def _row(item: ListingState, today: date) -> str:
    dagen = _dagen_bekend(item, today)
    is_nieuw = dagen == 0
    badges = []
    if is_nieuw:
        badges.append('<span class="badge badge-nieuw">nieuw vandaag</span>')
    if item.woz_check_nodig:
        badges.append('<span class="badge badge-check">check WOZ-waarde</span>')
    badges.append('<span class="badge badge-check">check zelfbewoningsplicht</span>')

    return f"""
    <tr>
      <td><a href="{escape(item.url)}">{escape(item.weergavenaam)}</a></td>
      <td>{escape(item.wijknaam or '-')}</td>
      <td>{dagen} dag{'en' if dagen != 1 else ''}</td>
      <td>{' '.join(badges)}</td>
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

  <h2>Openstaande kansen ({len(result.alle_actief)})</h2>
  <p class="small">
    Deze huizen zijn NIET afgevallen op nul-quotumgebied of de 50-meter kamerverhuurvergunning-check.
    "Dagen bekend" = dagen sinds dit systeem het huis voor het eerst zag in je Funda-alertmail (meestal
    gelijk aan de echte Funda-plaatsingsdatum, maar niet gegarandeerd exact).
    Elk huis heeft nog handmatige checks nodig — zie badges.
  </p>
  <table>
    <tr><th>Adres</th><th>Wijk</th><th>Dagen bekend</th><th>Nog te checken</th></tr>
    {actieve_rows or '<tr><td colspan="4">Geen openstaande kansen.</td></tr>'}
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
    Herinnering: "check WOZ-waarde" betekent opzoeken op
    <a href="https://www.wozwaardeloket.nl/">wozwaardeloket.nl</a> — bij een WOZ-waarde
    boven de opkoopbeschermingsgrens valt het huis NIET af. "check zelfbewoningsplicht" betekent
    kort de advertentietekst op funda doorlezen op dat woord (dit kan niet automatisch, funda blokkeert
    geautomatiseerd bezoek).
  </p>
</body>
</html>
"""


def build_text_report(result: RunResult, today: date) -> str:
    lines = [f"Kamerverhuur-scanner Rotterdam — {today.strftime('%d-%m-%Y')}", ""]
    lines.append(f"Openstaande kansen ({len(result.alle_actief)}):")
    for item in result.alle_actief:
        dagen = _dagen_bekend(item, today)
        extra = []
        if item.woz_check_nodig:
            extra.append("check WOZ-waarde")
        extra.append("check zelfbewoningsplicht")
        lines.append(f"- {item.weergavenaam} ({item.wijknaam or '-'}, {dagen} dagen bekend) {item.url}")
        lines.append(f"    nog te checken: {', '.join(extra)}")
    if not result.alle_actief:
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

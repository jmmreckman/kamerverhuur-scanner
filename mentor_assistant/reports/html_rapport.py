"""
HTML rapport generator voor de dagelijkse briefing.
Genereert een mooi leesbaar HTML bestand dat automatisch in de browser opent.
"""
from datetime import datetime
from pathlib import Path

RAPPORT_DIR = Path(__file__).parent.parent / "data" / "rapporten"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mentor Briefing – {datum_lang}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #f0f4f8;
    color: #2d3748;
    padding: 20px;
    max-width: 900px;
    margin: 0 auto;
  }}
  .header {{
    background: linear-gradient(135deg, #4a7c59, #2d5a3d);
    color: white;
    padding: 24px 28px;
    border-radius: 12px;
    margin-bottom: 20px;
  }}
  .header h1 {{ font-size: 1.6rem; font-weight: 600; }}
  .header .datum {{ opacity: 0.85; margin-top: 4px; font-size: 0.95rem; }}
  .intro-box {{
    background: white;
    border-left: 4px solid #4a7c59;
    padding: 16px 20px;
    border-radius: 8px;
    margin-bottom: 20px;
    font-size: 1.05rem;
    line-height: 1.6;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  }}
  .sectie {{
    background: white;
    border-radius: 10px;
    padding: 20px 24px;
    margin-bottom: 18px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  }}
  .sectie h2 {{
    font-size: 1.1rem;
    color: #4a7c59;
    border-bottom: 2px solid #e2e8f0;
    padding-bottom: 10px;
    margin-bottom: 14px;
  }}
  .bericht-kaart {{
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 14px 16px;
    margin-bottom: 12px;
    position: relative;
  }}
  .bericht-kaart:last-child {{ margin-bottom: 0; }}
  .bericht-meta {{
    font-size: 0.82rem;
    color: #718096;
    margin-bottom: 6px;
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
  }}
  .bericht-onderwerp {{ font-weight: 600; font-size: 1rem; margin-bottom: 6px; }}
  .bericht-samenvatting {{ color: #4a5568; line-height: 1.5; margin-bottom: 10px; }}
  .bericht-bron {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
  }}
  .bron-outlook {{ background: #dbeafe; color: #1e40af; }}
  .bron-teams {{ background: #ede9fe; color: #5b21b6; }}
  .bron-magister {{ background: #fef3c7; color: #92400e; }}
  .concept-mail {{
    background: #f0fdf4;
    border: 1px dashed #86efac;
    border-radius: 6px;
    padding: 12px 14px;
    margin-top: 10px;
    font-size: 0.9rem;
    white-space: pre-wrap;
    line-height: 1.5;
    color: #1a5c2a;
  }}
  .concept-label {{
    font-size: 0.75rem;
    font-weight: 600;
    color: #15803d;
    margin-bottom: 6px;
  }}
  .actie-badge {{
    position: absolute;
    top: 14px;
    right: 14px;
    background: #fef2f2;
    color: #b91c1c;
    font-size: 0.72rem;
    padding: 2px 8px;
    border-radius: 12px;
    font-weight: 600;
  }}
  .leerling-tag {{
    background: #e0f2fe;
    color: #0369a1;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 0.75rem;
    font-weight: 500;
  }}
  .agenda-item {{
    display: flex;
    gap: 14px;
    padding: 10px 0;
    border-bottom: 1px solid #f0f0f0;
  }}
  .agenda-item:last-child {{ border-bottom: none; }}
  .agenda-tijd {{
    font-weight: 600;
    color: #4a7c59;
    min-width: 90px;
    font-size: 0.9rem;
  }}
  .agenda-titel {{ flex: 1; }}
  .taak-rij {{
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 10px 0;
    border-bottom: 1px solid #f0f0f0;
  }}
  .taak-rij:last-child {{ border-bottom: none; }}
  .prioriteit-dot {{
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-top: 5px;
    flex-shrink: 0;
  }}
  .prio-urgent {{ background: #dc2626; }}
  .prio-hoog {{ background: #f59e0b; }}
  .prio-normaal {{ background: #10b981; }}
  .prio-laag {{ background: #94a3b8; }}
  .geen-items {{ color: #94a3b8; font-style: italic; text-align: center; padding: 16px; }}
  .footer {{
    text-align: center;
    color: #94a3b8;
    font-size: 0.8rem;
    margin-top: 20px;
    padding: 16px;
  }}
</style>
</head>
<body>

<div class="header">
  <h1>📋 Mentor Dagbriefing</h1>
  <div class="datum">{datum_lang}</div>
</div>

<div class="intro-box">{intro}</div>

<!-- AGENDA -->
<div class="sectie">
  <h2>🗓 Agenda vandaag ({n_agenda} item(s))</h2>
  {agenda_html}
</div>

<!-- BERICHTEN -->
<div class="sectie">
  <h2>📬 Nieuwe berichten ({n_berichten})</h2>
  {berichten_html}
</div>

<!-- TAKEN -->
<div class="sectie">
  <h2>✅ Openstaande taken ({n_taken})</h2>
  {taken_html}
</div>

<div class="footer">
  Gegenereerd op {tijdstip} door Mentor AI Assistent
</div>

</body>
</html>"""


def _format_datum(datum_str: str) -> str:
    """Formatteer ISO datum naar leesbare Nederlandse datum."""
    try:
        dt = datetime.fromisoformat(datum_str.replace("Z", "+00:00"))
        dagen = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
        maanden = ["januari", "februari", "maart", "april", "mei", "juni",
                   "juli", "augustus", "september", "oktober", "november", "december"]
        return f"{dagen[dt.weekday()]} {dt.day} {maanden[dt.month - 1]} {dt.year}"
    except Exception:
        return datum_str[:10] if datum_str else ""


def _agenda_html(agenda: list) -> str:
    if not agenda:
        return '<div class="geen-items">Geen agenda-items gevonden</div>'

    html = ""
    for item in agenda:
        start = item.get("start", "")
        tijd = start[11:16] if "T" in start else "Hele dag"
        locatie = f" — {item['locatie']}" if item.get("locatie") else ""
        html += f"""<div class="agenda-item">
  <div class="agenda-tijd">{tijd}</div>
  <div class="agenda-titel">{item['titel']}{locatie}</div>
</div>"""
    return html


def _berichten_html(berichten: list) -> str:
    if not berichten:
        return '<div class="geen-items">Geen nieuwe berichten</div>'

    html = ""
    for b in [dict(r) if not isinstance(r, dict) else r for r in berichten]:
        bron = b["bron"]
        leerling_naam = ""
        if b.get("voornaam"):
            leerling_naam = f"{b['voornaam']} {b['achternaam'] or ''}".strip()

        actie_badge = '<span class="actie-badge">↩ Actie vereist</span>' if b.get("actie_vereist") else ""

        leerling_tag = f'<span class="leerling-tag">👤 {leerling_naam}</span>' if leerling_naam else ""

        concept = ""
        if b.get("concept_reactie"):
            concept = f"""<div class="concept-label">✏ Concept antwoord:</div>
<div class="concept-mail">{b['concept_reactie']}</div>"""

        html += f"""<div class="bericht-kaart">
  {actie_badge}
  <div class="bericht-meta">
    <span class="bericht-bron bron-{bron}">{bron}</span>
    <span>van: {b.get('van_email') or 'onbekend'}</span>
    {leerling_tag}
  </div>
  <div class="bericht-onderwerp">{b.get('onderwerp') or '(geen onderwerp)'}</div>
  <div class="bericht-samenvatting">{b.get('samenvatting') or b.get('inhoud', '')[:300]}</div>
  {concept}
</div>"""

    return html


def _taken_html(taken: list) -> str:
    if not taken:
        return '<div class="geen-items">Geen openstaande taken</div>'

    html = ""
    for taak in taken:
        prio = taak.get("prioriteit", "normaal")
        naam = ""
        if taak.get("voornaam"):
            naam = f" — {taak['voornaam']} {taak['achternaam'] or ''}".strip()
        deadline = f" (vóór {taak['deadline']})" if taak.get("deadline") else ""

        html += f"""<div class="taak-rij">
  <div class="prioriteit-dot prio-{prio}"></div>
  <div><strong>{taak['titel']}</strong>{naam}{deadline}
  {'<br><small style="color:#718096">' + taak['beschrijving'] + '</small>' if taak.get('beschrijving') else ''}
  </div>
</div>"""

    return html


def genereer_html_rapport(intro: str, berichten: list, taken: list,
                           agenda: list, datum: str) -> str:
    """Genereer volledig HTML rapport."""
    datum_dt = datetime.strptime(datum, "%Y-%m-%d")
    dagen = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
    maanden = ["januari", "februari", "maart", "april", "mei", "juni",
               "juli", "augustus", "september", "oktober", "november", "december"]
    datum_lang = f"{dagen[datum_dt.weekday()]} {datum_dt.day} {maanden[datum_dt.month - 1]} {datum_dt.year}"

    html = HTML_TEMPLATE.format(
        datum_lang=datum_lang,
        intro=intro.replace("\n", "<br>"),
        n_agenda=len(agenda),
        agenda_html=_agenda_html(agenda),
        n_berichten=len(berichten),
        berichten_html=_berichten_html(berichten),
        n_taken=len(taken),
        taken_html=_taken_html(taken),
        tijdstip=datetime.now().strftime("%H:%M"),
    )

    # Sla op
    RAPPORT_DIR.mkdir(parents=True, exist_ok=True)
    rapport_pad = RAPPORT_DIR / f"briefing_{datum}.html"
    rapport_pad.write_text(html, encoding="utf-8")

    return html


def open_in_browser(datum: str = None):
    """Open het dagrapport in de standaard browser."""
    import webbrowser
    datum = datum or datetime.now().strftime("%Y-%m-%d")
    pad = RAPPORT_DIR / f"briefing_{datum}.html"
    if pad.exists():
        webbrowser.open(pad.as_uri())
    else:
        print(f"Rapport niet gevonden: {pad}")

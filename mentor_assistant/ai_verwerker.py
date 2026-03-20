"""
AI verwerker: gebruikt Gemini API voor:
  1. Koppelen van berichten aan leerlingen
  2. Samenvatten van berichten en documenten
  3. Genereren van conceptreacties (in de schrijfstijl van de mentor)
  4. Extraheren van taken
  5. Genereren van de dagelijkse briefing

Setup: zet GEMINI_API_KEY in config.py
Gratis API key via: https://aistudio.google.com/app/apikey
"""
import json
import re
import time
from datetime import datetime

import google.generativeai as genai

from .config import GEMINI_API_KEY, MENTOR_NAAM, MENTOR_SCHRIJFSTIJL
from .database import (
    get_alle_leerlingen,
    get_connection,
    get_contacten,
    get_onverwerkte_communicatie,
    get_sync_status,
    get_tijdlijn,
    voeg_tijdlijn_toe,
)

# Initialiseer Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")  # snel en goedkoop


def _vraag_ai(prompt: str, max_pogingen: int = 3) -> str:
    """Stuur een vraag naar Gemini met retry bij rate limit."""
    for poging in range(max_pogingen):
        try:
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                wacht = 2 ** poging * 5
                print(f"  Rate limit, wacht {wacht}s...")
                time.sleep(wacht)
            else:
                raise
    raise RuntimeError("Gemini API bereikbaar na meerdere pogingen.")


def _bouw_leerling_context(leerling_id: int) -> str:
    """Bouw een contextuele samenvatting van een leerling voor de AI prompt."""
    conn = get_connection()
    leerling = conn.execute(
        "SELECT * FROM leerlingen WHERE id = ?", (leerling_id,)
    ).fetchone()
    contacten = get_contacten(leerling_id)
    tijdlijn = get_tijdlijn(leerling_id, limit=10)
    conn.close()

    if not leerling:
        return ""

    naam = f"{leerling['voornaam']} {leerling['tussenvoegsel'] or ''} {leerling['achternaam']}".strip()
    ctx = f"LEERLING: {naam} | Klas: {leerling['klas']} | Leerjaar: {leerling['leerjaar']}\n"

    if leerling["notities"]:
        ctx += f"Achtergrond: {leerling['notities']}\n"

    if contacten:
        ctx += "Contacten:\n"
        for c in contacten:
            ctx += f"  - {c['rol']}: {c['voornaam']} {c['achternaam']} ({c['email'] or c['telefoon'] or 'geen contact'})\n"

    if tijdlijn:
        ctx += "Recente tijdlijn:\n"
        for t in tijdlijn:
            ctx += f"  [{t['datum']}] {t['type'].upper()}: {t['titel']}\n"
            if t["beschrijving"]:
                ctx += f"    {t['beschrijving'][:200]}\n"

    return ctx


def _maak_leerling_naam_lijst() -> str:
    """Maak een lijst van alle mentorleerlingen voor koppeling."""
    leerlingen = get_alle_leerlingen()
    return "\n".join(
        f"ID {l['id']}: {l['voornaam']} {l['tussenvoegsel'] or ''} {l['achternaam']} ({l['klas']})".strip()
        for l in leerlingen
    )


# ── Stap 1: koppel berichten aan leerlingen ───────────────────────────────────

def koppel_berichten_aan_leerlingen():
    """
    Voor elk onverwerkt bericht: bepaal via AI of het over een leerling gaat
    en zo ja, welke.
    """
    berichten = get_onverwerkte_communicatie()
    if not berichten:
        return

    leerling_lijst = _maak_leerling_naam_lijst()
    print(f"AI: koppelen van {len(berichten)} bericht(en) aan leerlingen...")

    conn = get_connection()

    for bericht in berichten:
        if not leerling_lijst:
            break

        prompt = f"""Je bent assistent van mentor {MENTOR_NAAM} op een voortgezet onderwijs school.

Mentorleerlingen:
{leerling_lijst}

Bericht (van: {bericht['van_email'] or 'onbekend'}):
Onderwerp: {bericht['onderwerp'] or '(geen)'}
Inhoud: {(bericht['inhoud'] or '')[:1000]}

Opdracht: Is dit bericht gerelateerd aan één van bovenstaande leerlingen?
Antwoord ALLEEN met JSON in dit formaat:
{{"leerling_id": <getal of null>, "zekerheid": "<hoog/gemiddeld/laag>", "reden": "<korte uitleg>"}}"""

        try:
            antwoord = _vraag_ai(prompt)
            # Extraheer JSON uit het antwoord
            json_match = re.search(r'\{[^}]+\}', antwoord, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                leerling_id = data.get("leerling_id")
                if leerling_id:
                    conn.execute(
                        "UPDATE communicatie SET leerling_id = ? WHERE id = ?",
                        (leerling_id, bericht["id"])
                    )
        except Exception as e:
            print(f"  ⚠ Koppeling bericht {bericht['id']}: {e}")

    conn.commit()
    conn.close()


# ── Stap 2: samenvatten en conceptreacties genereren ─────────────────────────

def verwerk_berichten_met_ai():
    """
    Genereer voor elk onverwerkt bericht:
    - Samenvatting
    - Conceptreactie (in schrijfstijl mentor)
    - Of actie vereist is
    """
    berichten = get_onverwerkte_communicatie()
    if not berichten:
        print("  Geen nieuwe berichten te verwerken.")
        return

    print(f"AI: verwerken van {len(berichten)} bericht(en)...")
    conn = get_connection()

    for bericht in berichten:
        leerling_context = ""
        if bericht["leerling_id"]:
            leerling_context = _bouw_leerling_context(bericht["leerling_id"])

        prompt = f"""Je bent de AI-assistent van {MENTOR_NAAM}, mentor en docent op een vrije school voor voortgezet onderwijs.

{f"Context over de betrokken leerling:{chr(10)}{leerling_context}" if leerling_context else ""}

INKOMEND BERICHT:
Van: {bericht['van_email'] or 'onbekend'}
Onderwerp: {bericht['onderwerp'] or '(geen onderwerp)'}
Datum: {bericht['datum']}
Inhoud:
{(bericht['inhoud'] or '')[:2000]}

Jouw taken:
1. Geef een korte samenvatting (2-3 zinnen) van dit bericht.
2. Bepaal of dit bericht een reactie vereist (ja/nee) en waarom.
3. Als reactie vereist: schrijf een concept-antwoord in de schrijfstijl van {MENTOR_NAAM}.

SCHRIJFSTIJL:
{MENTOR_SCHRIJFSTIJL}

Antwoord ALLEEN met JSON:
{{
  "samenvatting": "...",
  "actie_vereist": true/false,
  "reden_actie": "...",
  "concept_reactie": "..." of null
}}"""

        try:
            antwoord = _vraag_ai(prompt)
            json_match = re.search(r'\{[\s\S]+\}', antwoord)
            if json_match:
                data = json.loads(json_match.group())
                conn.execute("""
                    UPDATE communicatie
                    SET samenvatting = ?,
                        actie_vereist = ?,
                        concept_reactie = ?,
                        verwerkt = 1
                    WHERE id = ?
                """, (
                    data.get("samenvatting"),
                    1 if data.get("actie_vereist") else 0,
                    data.get("concept_reactie"),
                    bericht["id"],
                ))

                # Voeg toe aan tijdlijn als gekoppeld aan leerling
                if bericht["leerling_id"] and data.get("samenvatting"):
                    voeg_tijdlijn_toe(
                        leerling_id=bericht["leerling_id"],
                        datum=bericht["datum"][:10],
                        type_="mail",
                        titel=f"{bericht['bron'].capitalize()}: {bericht['onderwerp'] or 'bericht'}",
                        beschrijving=data["samenvatting"],
                        communicatie_id=bericht["id"],
                    )
        except Exception as e:
            print(f"  ⚠ Verwerking bericht {bericht['id']}: {e}")
            conn.execute(
                "UPDATE communicatie SET verwerkt = 1 WHERE id = ?",
                (bericht["id"],)
            )

    conn.commit()
    conn.close()
    print("  → AI verwerking compleet.")


# ── Stap 3: documenten samenvatten ───────────────────────────────────────────

def vat_documenten_samen():
    """Genereer AI-samenvattingen voor documenten met geëxtraheerde tekst."""
    conn = get_connection()
    docs = conn.execute("""
        SELECT d.id, d.bestandsnaam, d.volledige_tekst, l.voornaam, l.achternaam
        FROM documenten d
        JOIN leerlingen l ON d.leerling_id = l.id
        WHERE d.volledige_tekst IS NOT NULL
          AND d.volledige_tekst != ''
          AND (d.samenvatting IS NULL OR d.samenvatting = '')
        LIMIT 10
    """).fetchall()
    conn.close()

    if not docs:
        return

    print(f"AI: samenvatten van {len(docs)} document(en)...")
    conn = get_connection()

    for doc in docs:
        prompt = f"""Samenvatten van een schooldocument voor mentor {MENTOR_NAAM}.

Document: {doc['bestandsnaam']}
Leerling: {doc['voornaam']} {doc['achternaam']}

Tekst:
{doc['volledige_tekst'][:4000]}

Geef een bondige samenvatting (max 5 zinnen) van de belangrijkste punten.
Wat is de kern? Welke acties of besluiten zijn er?"""

        try:
            samenvatting = _vraag_ai(prompt)
            conn.execute(
                "UPDATE documenten SET samenvatting = ? WHERE id = ?",
                (samenvatting, doc["id"])
            )
        except Exception as e:
            print(f"  ⚠ Samenvatting {doc['bestandsnaam']}: {e}")

    conn.commit()
    conn.close()


# ── Stap 4: dagelijkse briefing genereren ────────────────────────────────────

def genereer_dagelijkse_briefing() -> str:
    """
    Genereer de dagelijkse HTML briefing met:
    - Agenda van vandaag
    - Overzicht van nieuwe berichten met conceptreacties
    - Openstaande taken
    - Aandachtspunten per leerling
    """
    from .connectors.google_calendar import get_agenda_vandaag
    from .reports.html_rapport import genereer_html_rapport

    print("AI: dagelijkse briefing genereren...")
    vandaag = datetime.now().strftime("%Y-%m-%d")

    conn = get_connection()

    # Berichten van vandaag/gisteren die verwerkt zijn
    berichten = conn.execute("""
        SELECT c.*, l.voornaam, l.achternaam
        FROM communicatie c
        LEFT JOIN leerlingen l ON c.leerling_id = l.id
        WHERE c.verwerkt = 1
          AND date(c.datum) >= date('now', '-1 day')
        ORDER BY c.datum DESC
    """).fetchall()

    # Open taken
    taken = conn.execute("""
        SELECT t.*, l.voornaam, l.achternaam
        FROM taken t
        LEFT JOIN leerlingen l ON t.leerling_id = l.id
        WHERE t.status = 'open'
        ORDER BY
            CASE t.prioriteit WHEN 'urgent' THEN 1 WHEN 'hoog' THEN 2 WHEN 'normaal' THEN 3 ELSE 4 END,
            t.deadline
        LIMIT 20
    """).fetchall()

    conn.close()

    agenda = get_agenda_vandaag()

    # Laat AI een intro-samenvatting schrijven
    bericht_overzicht = "\n".join(
        f"- {b['bron']}: {b['onderwerp'] or 'bericht'} van {b['van_email'] or 'onbekend'}"
        f" ({b['voornaam'] or '?'} {b['achternaam'] or ''})"
        for b in berichten[:10]
    )

    dag_prompt = f"""Maak een korte dagopening (3-5 zinnen) voor mentor {MENTOR_NAAM}.
Vandaag: {datetime.now().strftime('%A %d %B %Y')}

Agenda vandaag: {len(agenda)} item(s)
Nieuwe berichten: {len(berichten)}
{bericht_overzicht}
Open taken: {len(taken)}

Spreek de mentor direct aan, warm en concreet. Noem de highlights."""

    try:
        dag_intro = _vraag_ai(dag_prompt)
    except Exception:
        dag_intro = f"Goedemorgen {MENTOR_NAAM}! Hier is je overzicht voor vandaag."

    # Genereer HTML rapport
    html = genereer_html_rapport(
        intro=dag_intro,
        berichten=berichten,
        taken=taken,
        agenda=agenda,
        datum=vandaag,
    )

    # Sla op in database
    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO briefings (datum, inhoud_html, aangemaakt_op)
        VALUES (?, ?, datetime('now'))
    """, (vandaag, html))
    conn.commit()
    conn.close()

    print("  → Dagelijkse briefing gegenereerd.")
    return html

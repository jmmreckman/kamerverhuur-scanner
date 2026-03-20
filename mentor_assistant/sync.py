"""
Dagelijkse sync orchestrator.
Voert alle stappen in volgorde uit:
  1. Sync Outlook mails
  2. Sync Teams berichten
  3. Sync Magister berichten + documenten
  4. Sync Google Calendar
  5. Extraheer PDF teksten
  6. Koppel berichten aan leerlingen (Claude AI)
  7. Verwerk berichten met AI (samenvatten + conceptreacties)
  8. Vat documenten samen (Claude AI)
  9. Genereer dagelijkse HTML briefing
 10. Verstuur briefing als e-mail via Outlook

Draaien: python -m mentor_assistant.sync
Of automatisch via Windows Task Scheduler (zie installatie.bat)
"""
import sys
import traceback
from datetime import datetime


def voer_sync_uit():
    print(f"\n{'='*60}")
    print(f"  Mentor AI Assistent — Sync gestart: {datetime.now().strftime('%d-%m-%Y %H:%M')}")
    print(f"{'='*60}\n")

    fouten = []

    # ── Stap 1: Database initialiseren (idempotent) ──────────────────────────
    try:
        from .database import init_database
        init_database()
    except Exception as e:
        print(f"FOUT bij database init: {e}")
        sys.exit(1)

    # ── Stap 2: Gmail (doorgestuurde werk-mails) ─────────────────────────────
    try:
        from .connectors.gmail_imap import sync_gmail
        sync_gmail()
    except Exception as e:
        print(f"Gmail sync overgeslagen: {e}")
        fouten.append(f"Gmail: {e}")

    # ── Stap 3: Teams (overgeslagen — niet meer via Azure) ────────────────────
    # Teams sync vereist Microsoft Graph API die niet beschikbaar is.

    # ── Stap 4: Magister ──────────────────────────────────────────────────────
    try:
        from .connectors.magister import sync_magister
        sync_magister()
    except Exception as e:
        print(f"Magister sync overgeslagen: {e}")
        fouten.append(f"Magister: {e}")

    # ── Stap 5: Google Calendar ───────────────────────────────────────────────
    try:
        from .connectors.google_calendar import sync_google_calendar
        sync_google_calendar()
    except Exception as e:
        print(f"Google Calendar sync overgeslagen: {e}")
        fouten.append(f"Google Calendar: {e}")

    # ── Stap 6: PDF teksten extraheren ────────────────────────────────────────
    try:
        from .connectors.pdf_verwerker import verwerk_onverwerkte_pdfs
        verwerk_onverwerkte_pdfs()
    except Exception as e:
        print(f"PDF verwerking overgeslagen: {e}")
        fouten.append(f"PDF: {e}")

    # ── Stap 7: AI – koppel berichten aan leerlingen ──────────────────────────
    try:
        from .ai_verwerker import koppel_berichten_aan_leerlingen
        koppel_berichten_aan_leerlingen()
    except Exception as e:
        print(f"AI koppeling overgeslagen: {e}")
        fouten.append(f"AI koppeling: {e}")

    # ── Stap 8: AI – berichten verwerken ──────────────────────────────────────
    try:
        from .ai_verwerker import verwerk_berichten_met_ai
        verwerk_berichten_met_ai()
    except Exception as e:
        print(f"AI berichtverwerking overgeslagen: {e}")
        fouten.append(f"AI berichten: {e}")

    # ── Stap 9: AI – documenten samenvatten ───────────────────────────────────
    try:
        from .ai_verwerker import vat_documenten_samen
        vat_documenten_samen()
    except Exception as e:
        print(f"Documentsamenvatting overgeslagen: {e}")
        fouten.append(f"AI documenten: {e}")

    # ── Stap 10: Dagelijkse briefing genereren ────────────────────────────────
    html = None
    try:
        from .ai_verwerker import genereer_dagelijkse_briefing
        html = genereer_dagelijkse_briefing()
    except Exception as e:
        print(f"Briefing genereren mislukt: {e}")
        traceback.print_exc()
        fouten.append(f"Briefing: {e}")

    # ── Stap 11: Verstuur briefing als e-mail ─────────────────────────────────
    if html:
        try:
            from .connectors.gmail_imap import verstuur_briefing_email
            vandaag = datetime.now().strftime("%d-%m-%Y")
            dag = datetime.now().strftime("%A")
            verstuur_briefing_email(
                onderwerp=f"Mentor Briefing {dag} {vandaag}",
                html_body=html,
            )
        except Exception as e:
            print(f"Briefing e-mail versturen mislukt: {e}")
            traceback.print_exc()
            fouten.append(f"Email: {e}")

            # Fallback: sla op als lokaal bestand
            try:
                from .reports.html_rapport import RAPPORT_DIR
                RAPPORT_DIR.mkdir(parents=True, exist_ok=True)
                pad = RAPPORT_DIR / f"briefing_{datetime.now().strftime('%Y-%m-%d')}.html"
                pad.write_text(html, encoding="utf-8")
                print(f"  Briefing opgeslagen als: {pad}")
            except Exception:
                pass

    # ── Samenvatting ─────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    if fouten:
        print(f"  Sync klaar met {len(fouten)} waarschuwing(en):")
        for f in fouten:
            print(f"    - {f}")
    else:
        print("  Sync succesvol afgerond! Briefing gemaild.")
    print(f"  Tijd: {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    voer_sync_uit()

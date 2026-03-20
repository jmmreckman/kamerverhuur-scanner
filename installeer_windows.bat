@echo off
:: ============================================================
:: Mentor AI Assistent — Windows Installatie Script
:: Dubbelklik dit bestand om te installeren
:: ============================================================

echo.
echo  ============================================================
echo   Mentor AI Assistent — Installatie
echo  ============================================================
echo.

:: Controleer Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  FOUT: Python niet gevonden!
    echo  Download Python van https://python.org/downloads
    echo  Zorg dat je "Add Python to PATH" aanvinkt!
    pause
    exit /b 1
)

echo  [1/4] Python dependencies installeren...
pip install requests google-generativeai google-auth-oauthlib google-api-python-client pdfplumber pymupdf schedule >installatie_log.txt 2>&1
if errorlevel 1 (
    echo  FOUT bij installeren. Zie installatie_log.txt
    pause
    exit /b 1
)
echo  OK: dependencies geinstalleerd.

echo.
echo  [2/4] Data mappen aanmaken...
mkdir mentor_assistant\data 2>nul
mkdir mentor_assistant\data\rapporten 2>nul
mkdir mentor_assistant\data\magister_docs 2>nul
echo  OK: mappen aangemaakt.

echo.
echo  [3/4] Instellen Windows Taakplanner (elke ochtend 07:00)...
:: Verwijder oude taak als die bestaat
schtasks /delete /tn "MentorAIAssistent" /f >nul 2>&1

:: Haal het huidige pad op
set SCRIPT_DIR=%~dp0
set PYTHON_SCRIPT=%SCRIPT_DIR%start_sync.bat

:: Maak de geplande taak aan
schtasks /create /tn "MentorAIAssistent" /tr "\"%PYTHON_SCRIPT%\"" /sc DAILY /st 07:00 /ru "%USERNAME%" /rl HIGHEST /f
if errorlevel 1 (
    echo  WAARSCHUWING: Taakplanner instellen mislukt.
    echo  Je kunt start_sync.bat handmatig uitvoeren.
) else (
    echo  OK: Dagelijkse sync gepland om 07:00.
)

echo.
echo  [4/4] Google Calendar eerste login...
echo  (Er opent een browser voor toestemming)
echo  Dit is eenmalig nodig.
echo.
echo  Druk op een toets om door te gaan...
pause >nul
python -m mentor_assistant.connectors.google_calendar

echo.
echo  ============================================================
echo   Installatie klaar!
echo  ============================================================
echo.
echo   Volgende stappen:
echo   1. Open mentor_assistant\config.py en vul jouw gegevens in
echo   2. Voer start_sync.bat eenmalig uit om Outlook/Teams te koppelen
echo   3. Daarna draait het systeem elke ochtend om 07:00 automatisch
echo.
echo   Zie README.md voor uitgebreide instructies.
echo.
pause

@echo off
cd /d "%~dp0"

if not exist venv (
    echo Eerste keer opstarten: virtuele omgeving aanmaken...
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate.bat
)

echo.
echo ============================================================
echo  Gewicht Tracker start op poort 8420.
echo  Vind het lokale IP-adres van deze pc met: ipconfig
echo  Open op je telefoon (zelfde wifi): http://^<dit-ip^>:8420
echo ============================================================
echo.

uvicorn app:app --host 0.0.0.0 --port 8420
pause

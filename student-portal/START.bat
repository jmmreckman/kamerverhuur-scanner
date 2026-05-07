@echo off
title Mentorlessen Portaal
color 0A
echo.
echo  ==========================================
echo   Mentorlessen Portaal wordt gestart...
echo  ==========================================
echo.

REM Controleer of Python beschikbaar is
python --version >nul 2>&1
if errorlevel 1 (
    echo FOUT: Python is niet gevonden!
    echo Installeer Python via https://www.python.org/downloads/
    echo Vink bij installatie "Add Python to PATH" aan!
    pause
    exit /b 1
)

REM Installeer Flask als die er nog niet is
echo Flask controleren en installeren...
pip install flask --quiet

echo.
echo  Portaal draait op: http://localhost:5000
echo  Docent-pagina:     http://localhost:5000/docent
echo.
echo  Laat dit venster OPEN tijdens de les!
echo  Sluit het om te stoppen.
echo.

REM Start de server
python app.py
pause

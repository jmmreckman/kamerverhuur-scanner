@echo off
:: Voer dit uit als Administrator (rechtsklik → Als administrator uitvoeren)
echo Taakplanner instellen...
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0stel_taakplanner_in.ps1"

echo.
if %ERRORLEVEL% == 0 (
    echo GELUKT! Sync draait voortaan elke ochtend om 06:00.
) else (
    echo FOUT - zie rode tekst hierboven.
    echo Probeer: rechtsklik op dit bestand en kies "Als administrator uitvoeren"
)

echo.
pause

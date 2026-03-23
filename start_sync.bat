@echo off
:: Start de dagelijkse Mentor AI sync
:: Dit bestand wordt door Windows Taakplanner elke ochtend om 06:00 aangeroepen.
:: Je kunt het ook handmatig dubbelklikken.

cd /d "%~dp0"
python -m mentor_assistant.sync >> mentor_assistant\data\sync_log.txt 2>&1

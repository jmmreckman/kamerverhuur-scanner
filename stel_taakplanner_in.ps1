# Stel_taakplanner_in.ps1
# Voer dit éénmalig uit als Administrator om de dagelijkse sync in te plannen.
# Rechtsklik het bestand → "Uitvoeren met PowerShell" (als administrator)

$projectmap = Split-Path -Parent $MyInvocation.MyCommand.Path
$batBestand = Join-Path $projectmap "start_sync.bat"

if (-not (Test-Path $batBestand)) {
    Write-Error "start_sync.bat niet gevonden in $projectmap"
    exit 1
}

$actie = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$batBestand`""

$trigger = New-ScheduledTaskTrigger `
    -Daily `
    -At "06:00"

$instellingen = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask `
    -TaskName "MentorHulp - Dagelijkse sync" `
    -Action $actie `
    -Trigger $trigger `
    -Settings $instellingen `
    -Description "Dagelijkse AI-briefing voor Jurian — leest Gmail, Magister en Google Calendar uit en stuurt samenvatting." `
    -RunLevel Highest `
    -Force

Write-Host ""
Write-Host "Taak aangemaakt! De sync draait nu elke ochtend om 06:00."
Write-Host "Controleren: open Taakplanner > Taakplannerbibliotheek > 'MentorHulp - Dagelijkse sync'"
Write-Host ""

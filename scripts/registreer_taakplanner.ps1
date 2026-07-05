# Registreert de dagelijkse Rotterdam kamerverhuur-scanner in Windows Taakplanner.
# Draai dit script vanuit een gewone PowerShell (geen admin nodig) op de zolder-pc:
#   cd pad\naar\kamerverhuur-scanner
#   .\scripts\registreer_taakplanner.ps1

param(
    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot),
    [string]$PythonExe = "python"
)

$taskName = "KamerverhuurScannerRotterdam"
$scriptPath = Join-Path $ProjectPath "main.py"
$venvPython = Join-Path $ProjectPath "venv\Scripts\python.exe"

if (Test-Path $venvPython) {
    $PythonExe = $venvPython
}

if (-not (Test-Path $scriptPath)) {
    Write-Error "Kan main.py niet vinden op $scriptPath. Geef -ProjectPath mee als de map elders staat."
    exit 1
}

$action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$scriptPath`"" -WorkingDirectory $ProjectPath
$trigger = New-ScheduledTaskTrigger -Daily -At 9:00am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Dagelijkse Rotterdam kamerverhuur-scanner (funda-alert + gemeente-checks)" -Force

Write-Host "Taak '$taskName' geregistreerd: draait dagelijks om 09:00 met $PythonExe."
Write-Host "Test hem direct met: Start-ScheduledTask -TaskName '$taskName'"
Write-Host "Logs verschijnen in de Windows Taakplanner-geschiedenis en in data\scanner.log (zie README)."

# Verwijdert de geplande taak weer, bijvoorbeeld om opnieuw te registreren met
# andere instellingen.

Unregister-ScheduledTask -TaskName "KamerverhuurScannerRotterdam" -Confirm:$false
Write-Host "Taak 'KamerverhuurScannerRotterdam' verwijderd."

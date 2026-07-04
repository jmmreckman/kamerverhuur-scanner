# Gewicht Tracker

Kleine webapp die op je zolder-pc draait en die je vanaf je telefoon
gebruikt (zelfde thuis-wifi) om je gewicht bij te houden.

## Eenmalig instellen op de zolder-pc (Windows)

1. Zorg dat [Python](https://www.python.org/downloads/) geïnstalleerd is
   (vink tijdens installatie "Add Python to PATH" aan).
2. Zet deze map op de pc (via `git clone`/`git pull` zoals je gewend bent).
3. Importeer je bestaande Excel-historie (eenmalig):
   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   python import_excel.py "C:\pad\naar\jouw\gewicht.xlsx"
   ```
   Verwacht formaat: kolom A = datum, kolom B = gewicht in kg. Een
   eventuele header-rij wordt automatisch overgeslagen.

## Dagelijks gebruik

Dubbelklik op `run.bat`. Dat opent een venster met daarin het lokale
IP-adres nodig om de app op je telefoon te openen (te vinden met
`ipconfig`, kijk bij "IPv4-adres"), bijvoorbeeld:

```
http://192.168.1.23:8420
```

Zet die URL als favoriet/homescreen-icoon op je telefoon. De pc moet aan
staan en de app moet via `run.bat` draaien; je telefoon moet op hetzelfde
wifi-netwerk zitten.

## Hoe het werkt

- Je vult alleen een gewicht in op de dagen dat je meet. De dagen ertussen
  worden automatisch lineair geïnterpoleerd (rechte lijn tussen twee
  metingen) en opgeslagen, zodat de grafieken een vloeiend verloop tonen.
- **Totaalgrafiek 2013-nu**: één lijn met alle data.
- **Per kalenderjaar**: elk jaar een eigen kleur, uitgezet op dag-van-het-jaar
  zodat je jaren onderling kan vergelijken.
- **Vergelijk vandaag**: je huidige gewicht tegenover dezelfde kalenderdag in
  alle voorgaande jaren, met per jaar of je toen zwaarder of lichter was.

## Later ergens anders bij kunnen (buiten je wifi)

Nu werkt de app alleen binnen je thuisnetwerk. Als je later ook onderweg
gewicht wil kunnen invullen, is [Tailscale](https://tailscale.com/) de
makkelijkste volgende stap (gratis, installeren op pc + telefoon, geen
open poorten nodig op je router) — laat het weten als je dat wil toevoegen.

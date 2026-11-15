"""Zelfbewoning/clausule-signalen uit de advertentietekst voor kansen.steenhub.nl.

Let op het onderscheid - een platte "bevat het woord zelfbewoning"-scan geeft hier
juist vals-positieven:
- **zelfbewoningsplicht** (restrictief): je móét er zelf wonen -> slecht voor verhuur.
- **niet-zelfbewoningsclausule** (gunstig): expliciet GEEN zelfbewoningsplicht -> prima
  voor een belegger. Bevat ook het woord "zelfbewoning", maar betekent het omgekeerde.
- **anti-speculatiebeding / kettingbeding**: verkoop-/verhuurbeperking, apart risico.

Dit is de *contractuele* zelfbewoning die in de tekst staat. De *gemeentelijke*
zelfbewoningsplicht (opkoopbescherming: wijk + WOZ) staat vrijwel nooit in de tekst en
wordt apart berekend (zie opkoop.py). "Niet in de tekst" betekent dus NIET "geen
zelfbewoningsplicht" - de twee signalen zijn aanvullend.

Pure functies, geen externe dependencies, los testbaar.
"""
from __future__ import annotations

import re

# Restrictieve zelfbewoningsplicht (je moet er zelf wonen).
_PLICHT_PATRONEN = [
    r"zelfbewoningsplicht",
    r"zelf\s*bewoningsplicht",
    r"zelfbewoningsclausule",
    r"plicht\s+tot\s+zelfbewoning",
    r"verplichting\s+tot\s+zelfbewoning",
    r"zelf\s+te\s+bewonen",
    r"zelf\s+bewonen\s+verplicht",
    r"eigen\s+bewoning\s+verplicht",
    r"verplichte\s+eigen\s+bewoning",
]
_PLICHT_RE = re.compile("|".join(_PLICHT_PATRONEN), re.IGNORECASE)

# Expliciet GEEN zelfbewoningsplicht (gunstig). Deze knippen we uit de tekst vóórdat we
# op de plicht scannen, zodat "niet-zelfbewoningsclausule" niet als plicht telt.
_NIET_RE = re.compile(
    r"niet[-\s]*zelfbewonings?(?:plicht|clausule)"
    r"|geen\s+zelfbewoningsplicht"
    r"|zonder\s+zelfbewoningsplicht"
    r"|niet[-\s]*zelf\s+te\s+bewonen",
    re.IGNORECASE,
)

# Anti-speculatie / kettingbeding (verkoop-/verhuurbeperking).
_ANTI_RE = re.compile(r"anti[-\s]*speculatie|antispeculatie|speculatiebeding|kettingbeding", re.IGNORECASE)


def classificeer_zelfbewoning(advertentietekst: str | None) -> dict:
    """Geeft de drie signalen terug:
    {"zelfbewoningsplicht": bool, "niet_zelfbewoningsclausule": bool, "anti_speculatie": bool}.
    De 'niet'-varianten worden uit de tekst verwijderd vóór de plicht-scan, zodat een
    niet-zelfbewoningsclausule niet onterecht als plicht telt."""
    t = advertentietekst or ""
    niet = bool(_NIET_RE.search(t))
    zonder_niet = _NIET_RE.sub(" ", t)
    plicht = bool(_PLICHT_RE.search(zonder_niet))
    anti = bool(_ANTI_RE.search(t))
    return {
        "zelfbewoningsplicht": plicht,
        "niet_zelfbewoningsclausule": niet,
        "anti_speculatie": anti,
    }


def bevat_zelfbewoningsplicht(advertentietekst: str | None) -> bool:
    """Backward-compatibel: alleen de restrictieve zelfbewoningsplicht (zonder de
    gunstige niet-clausules)."""
    return classificeer_zelfbewoning(advertentietekst)["zelfbewoningsplicht"]

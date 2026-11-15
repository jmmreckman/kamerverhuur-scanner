"""Erfpacht vs. eigen grond bepalen voor het eigendoms-filter op kansen.steenhub.nl.

Primaire bron is het gestructureerde Move-kenmerk *Eigendomssituatie* (waarden als
"Volle eigendom" / "Erfpacht"); de advertentietekst is het vangnet voor de nuance die
daar vaak níét in staat maar wel belangrijk is: of erfpacht **afgekocht** is (al dan
niet eeuwigdurend) en of er een lopende canon genoemd wordt. Een afgekochte erfpacht
is financieel vrijwel als eigen grond (geen doorlopende canon), een lopende/oplopende
of particuliere erfpacht is juist een risico - vandaar dat we die apart onderscheiden
in plaats van een platte ja/nee.

Pure functies, geen externe dependencies, dus los testbaar (sandbox-proof).
"""
from __future__ import annotations

import re

# Waardes die het Move-veld "Eigendomssituatie" kan aannemen (NVM-standaard).
_EIGEN_RE = re.compile(r"\b(volle?|vol)\s+eigendom\b|\beigen\s+grond\b", re.IGNORECASE)
_ERFPACHT_RE = re.compile(r"erfpacht", re.IGNORECASE)
# Afgekocht (eeuwigdurend of voor een periode) -> feitelijk geen doorlopende canon.
_AFGEKOCHT_RE = re.compile(r"afgekocht|afkoop|eeuwigdurend\s+afgekocht", re.IGNORECASE)
# Lopende canon (bedrag per periode) -> een doorlopende last.
_CANON_RE = re.compile(r"\bcanon\b", re.IGNORECASE)

# Uitkomst-categorieën.
EIGEN_GROND = "eigen_grond"
ERFPACHT = "erfpacht"
ERFPACHT_AFGEKOCHT = "erfpacht_afgekocht"
ONBEKEND = "onbekend"


def classificeer_eigendom(eigendomssituatie: str | None, tekst: str = "") -> dict:
    """Bepaalt het eigendomssoort uit het gestructureerde veld + de advertentietekst.

    Geeft: {"soort": EIGEN_GROND|ERFPACHT|ERFPACHT_AFGEKOCHT|ONBEKEND,
             "afgekocht": bool, "canon_genoemd": bool}.
    Het gestructureerde veld is leidend; de tekst verfijnt (afgekocht/canon) en vult
    aan als het veld leeg is."""
    veld = (eigendomssituatie or "").strip()
    t = tekst or ""
    afgekocht = bool(_AFGEKOCHT_RE.search(veld) or _AFGEKOCHT_RE.search(t))
    canon = bool(_CANON_RE.search(veld) or _CANON_RE.search(t))

    is_erfpacht = bool(_ERFPACHT_RE.search(veld))
    is_eigen = bool(_EIGEN_RE.search(veld))

    if not veld:  # geen gestructureerd veld -> op de tekst terugvallen
        if _ERFPACHT_RE.search(t):
            is_erfpacht = True
        elif _EIGEN_RE.search(t):
            is_eigen = True

    if is_erfpacht:
        soort = ERFPACHT_AFGEKOCHT if afgekocht else ERFPACHT
    elif is_eigen:
        soort = EIGEN_GROND
    else:
        soort = ONBEKEND

    return {"soort": soort, "afgekocht": afgekocht, "canon_genoemd": canon}

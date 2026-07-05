from __future__ import annotations

import re

_PATTERNS = [
    r"zelfbewoningsplicht",
    r"zelf\s*bewoningsplicht",
    r"plicht\s+tot\s+zelfbewoning",
    r"verplichting\s+tot\s+zelfbewoning",
    r"zelf\s+te\s+bewonen",
    r"zelf\s+bewonen\s+verplicht",
    r"eigen\s+bewoning\s+verplicht",
    r"verplichte\s+eigen\s+bewoning",
]

_COMBINED = re.compile("|".join(_PATTERNS), re.IGNORECASE)


def bevat_zelfbewoningsplicht(advertentietekst: str) -> bool:
    return bool(_COMBINED.search(advertentietekst or ""))

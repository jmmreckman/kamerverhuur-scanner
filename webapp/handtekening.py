"""Validatie van een canvas-handtekening (data-URL) tot een opslag-klare base64-
payload. Losse, lichte module zodat zowel de huurcontract-ondertekening
(ondertekenen.py) als het losse tekenportaal (tekenportaal.py) dit kunnen
gebruiken zonder elkaars zware contract-/PDF-afhankelijkheden binnen te halen."""
from __future__ import annotations

import base64
import binascii

_HANDTEKENING_DATA_URL_PREFIX = "data:image/png;base64,"
# Ruim voldoende voor een getekende handtekening op een canvas van realistische
# afmetingen (een 600x180px PNG met handtekening is doorgaans een paar KB) -
# voorkomt dat iemand een absurd grote afbeelding als "handtekening" post.
_MAX_HANDTEKENING_BYTES = 300_000


def handtekening_base64_uit_data_url(data_url: str) -> str | None:
    """Valideert en normaliseert een canvas-handtekening (data-URL) tot de kale
    base64-payload voor opslag. Geeft None terug bij een ontbrekende, ongeldige
    of te grote afbeelding."""
    if not data_url or not data_url.startswith(_HANDTEKENING_DATA_URL_PREFIX):
        return None
    payload = data_url[len(_HANDTEKENING_DATA_URL_PREFIX):]
    try:
        ruwe_bytes = base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error):
        return None
    if not ruwe_bytes or len(ruwe_bytes) > _MAX_HANDTEKENING_BYTES:
        return None
    return payload

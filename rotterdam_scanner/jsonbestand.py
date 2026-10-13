"""Atomair JSON-bestand schrijven.

Waarom: de state-bestanden (state.json, listings_archief.json, logboek.json en de
kleine voorkeur-/account-bestanden) werden met een gewone `open(..., "w")` /
`write_text` geschreven. Dat kapt het bestand éérst af en schrijft dan de inhoud.
Als het proces precies tijdens die schrijf sneuvelt - een container die bij een
deploy wordt gestopt, of een OOM-kill op de krappe VPS - blijft er een leeg of
half-geschreven bestand achter. Een lader die de JSON-fout stil opvangt (zoals het
logboek) maakt er vervolgens een vers, leeg bestand van: data weg.

`schrijf_json_atomisch` schrijft eerst naar een tijdelijk bestand in dezelfde map,
flusht + fsync't dat naar schijf en hernoemt het dan met os.replace(). Een rename
binnen één filesystem is ondeelbaar: elke lezer ziet óf het volledige oude, óf het
volledige nieuwe bestand - nooit een afgekapte tussenvorm.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def schrijf_json_atomisch(pad, data, *, indent: int = 2) -> None:
    """Serialiseer `data` als JSON en schrijf het atomair naar `pad`."""
    pad = Path(pad)
    pad.parent.mkdir(parents=True, exist_ok=True)
    tekst = json.dumps(data, indent=indent, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(dir=str(pad.parent), prefix=pad.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as bestand:
            bestand.write(tekst)
            bestand.flush()
            os.fsync(bestand.fileno())
        os.replace(tmp, pad)
    except BaseException:
        # Laat nooit een halfgeschreven temp-bestand achter.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

"""Bijhoudt de status van een handmatig gestarte "Totale sweep" (de volledige
wekelijkse Apify-scan, handmatig getriggerd vanaf kansen.steenhub.nl) in een
los bestand naast state.json.

Waarom een bestand i.p.v. gewoon een Python-variabele in het geheugen van de
Flask-app? De sweep draait in een achtergrondthread, losgekoppeld van de HTTP-
aanvraag die 'm gestart heeft - een lang openstaande fetch() wordt op mobiel
al snel onderbroken zodra de gebruiker van tabblad wisselt (bv. om de Apify-
billing te checken), waarna de browser "mislukt" toont terwijl de run bij
Apify gewoon (en dus tegen betaling) doorloopt. Door de status in een bestand
te zetten kan de website 'm blijven opvragen (pollen) via een aparte route,
ongeacht welke gunicorn-worker de aanvraag afhandelt en ongeacht of de
oorspronkelijke verbinding nog leeft."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .config import Config

_STATUSSEN = {"idle", "bezig", "klaar", "mislukt"}


@dataclass
class SweepStatus:
    status: str = "idle"
    gestart_op: str | None = None
    klaar_op: str | None = None
    nieuw_actief: int = 0
    nieuw_afgevallen: int = 0
    fouten: list[str] = field(default_factory=list)


def _pad(config: Config) -> Path:
    return Path(config.state_path).parent / "sweep_status.json"


def laad(config: Config) -> SweepStatus:
    pad = _pad(config)
    if not pad.is_file():
        return SweepStatus()
    try:
        ruw = json.loads(pad.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return SweepStatus()
    if not isinstance(ruw, dict) or ruw.get("status") not in _STATUSSEN:
        return SweepStatus()
    velden = {veld.name for veld in SweepStatus.__dataclass_fields__.values()}
    return SweepStatus(**{k: v for k, v in ruw.items() if k in velden})


def _sla_op(config: Config, status: SweepStatus) -> None:
    pad = _pad(config)
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text(json.dumps(asdict(status), indent=2, ensure_ascii=False), encoding="utf-8")


def zet_bezig(config: Config) -> None:
    _sla_op(config, SweepStatus(status="bezig", gestart_op=datetime.now().isoformat()))


def zet_klaar(config: Config, nieuw_actief: int, nieuw_afgevallen: int, fouten: list[str]) -> None:
    bestaand = laad(config)
    _sla_op(config, SweepStatus(
        status="klaar", gestart_op=bestaand.gestart_op, klaar_op=datetime.now().isoformat(),
        nieuw_actief=nieuw_actief, nieuw_afgevallen=nieuw_afgevallen, fouten=fouten,
    ))


def zet_mislukt(config: Config, fout: str) -> None:
    bestaand = laad(config)
    _sla_op(config, SweepStatus(
        status="mislukt", gestart_op=bestaand.gestart_op, klaar_op=datetime.now().isoformat(),
        fouten=[fout],
    ))

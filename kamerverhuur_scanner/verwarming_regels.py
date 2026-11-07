"""Regel-engine voor de vriendelijke terugschakeling ("gewoonte").

Pure logica, los testbaar - geen netwerk, geen database. De poll-service
(scripts/verwarming_check.py) leest de huidige stand + de opgeslagen
terugschakel-status, roept `beslis()` aan, en voert de uitkomst uit (overlay
zetten) + slaat de nieuwe status op.

Het idee (voorbeeld-instelling): zodra de huurder een kamer op of boven het
plafond (bv. 25°) zet, bouwt de service elke `interval_min` minuten een `stap`
graad af tot de `vloer_temp` (bv. 20°), en na `na_uren` uur hoog zakt het naar
`nacht_temp` (bv. 18°). De fysieke knop blijft werken: zet de huurder 'm zelf
lager dan waar wij zitten, dan laten we de regel los (hij wil het kouder).

Belangrijk: wij houden zélf bij sinds wanneer de afbouw loopt en wat we als
laatste hebben gezet, want het verlagen van het setpoint zou anders de
"staat al hoog"-detectie meteen wissen.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .verwarming_db import (
    SENSOR_MAX, SENSOR_MIN, STANDAARD_INTERVAL_MIN, STANDAARD_MAX,
    STANDAARD_NA_UREN, STANDAARD_NACHT, STANDAARD_STAP, STANDAARD_VLOER,
)

# Marge waarbinnen we een setpoint als "gelijk" beschouwen (Tado-knop verspringt
# in halve/hele graden; voorkomt heen-en-weer schrijven op afrondruis).
_EPS = 0.1


def sensor_ok(inside) -> bool:
    """Of een gemeten binnentemperatuur plausibel is om op te sturen."""
    return inside is not None and SENSOR_MIN <= inside <= SENSOR_MAX


@dataclass(frozen=True)
class Regel:
    max_temp: float = STANDAARD_MAX
    stap: float = STANDAARD_STAP
    interval_min: int = STANDAARD_INTERVAL_MIN
    vloer_temp: float = STANDAARD_VLOER
    na_uren: int | None = STANDAARD_NA_UREN
    nacht_temp: float | None = STANDAARD_NACHT

    @staticmethod
    def uit_row(row) -> "Regel":
        """Bouwt een Regel uit een zone_config-rij, met standaarden waar leeg."""
        def g(key, default):
            try:
                v = row[key]
            except (KeyError, IndexError, TypeError):
                v = None
            return default if v is None else v
        return Regel(
            max_temp=float(g("max_temp", STANDAARD_MAX)),
            stap=float(g("stap", STANDAARD_STAP)),
            interval_min=int(g("interval_min", STANDAARD_INTERVAL_MIN)),
            vloer_temp=float(g("vloer_temp", STANDAARD_VLOER)),
            na_uren=(None if g("na_uren", STANDAARD_NA_UREN) in (None, "") else int(g("na_uren", STANDAARD_NA_UREN))),
            nacht_temp=(None if g("nacht_temp", STANDAARD_NACHT) in (None, "") else float(g("nacht_temp", STANDAARD_NACHT))),
        )

    def geldig(self) -> bool:
        return (
            self.max_temp and self.vloer_temp
            and self.vloer_temp <= self.max_temp
            and self.stap > 0 and self.interval_min > 0
        )


@dataclass(frozen=True)
class Beslissing:
    nieuw_doel: float | None          # setpoint om te zetten (None = niets sturen)
    actief_sinds: datetime | None     # nieuwe terugschakel-status (None = niet actief)
    laatste_doel: float | None
    reden: str


def _doel_bij_verstreken(regel: Regel, minuten: float) -> float:
    stappen = int(minuten // regel.interval_min)
    doel = regel.max_temp - stappen * regel.stap
    if doel < regel.vloer_temp:
        doel = regel.vloer_temp
    if regel.na_uren is not None and regel.nacht_temp is not None and minuten >= regel.na_uren * 60:
        doel = regel.nacht_temp
    return round(doel, 1)


def beslis(regel: Regel, huidige_setpoint, nu: datetime,
           actief_sinds: datetime | None, laatste_doel) -> Beslissing:
    """Bepaalt wat er met deze zone moet gebeuren.

    - huidige_setpoint: het nu ingestelde setpoint (None = kamer staat uit).
    - actief_sinds/laatste_doel: de opgeslagen terugschakel-status (of None).
    """
    if not regel.geldig():
        return Beslissing(None, None, None, "regel ongeldig/onvolledig")

    if huidige_setpoint is None:
        return Beslissing(None, None, None, "kamer staat uit")

    # Nog niet bezig met afbouwen.
    if actief_sinds is None:
        if huidige_setpoint >= regel.max_temp - _EPS:
            # Start de afbouw. Staat 'ie boven het plafond, cap dan meteen terug.
            if huidige_setpoint > regel.max_temp + _EPS:
                return Beslissing(regel.max_temp, nu, regel.max_temp,
                                  "boven plafond - teruggezet naar max, afbouw gestart")
            return Beslissing(None, nu, regel.max_temp, "op plafond - afbouw gestart")
        return Beslissing(None, None, None, "onder plafond - niets te doen")

    # Afbouw loopt. Heeft de huurder zelf lager gezet dan waar wij zitten? Dan
    # wil hij het kouder - regel loslaten.
    if laatste_doel is not None and huidige_setpoint < laatste_doel - _EPS:
        return Beslissing(None, None, None, "huurder zelf lager gezet - regel losgelaten")

    minuten = max(0.0, (nu - actief_sinds).total_seconds() / 60.0)
    doel = _doel_bij_verstreken(regel, minuten)

    if laatste_doel is not None and abs(doel - laatste_doel) < _EPS:
        # Niets te wijzigen, maar status vasthouden.
        return Beslissing(None, actief_sinds, laatste_doel, "afbouw loopt - geen wijziging")

    return Beslissing(doel, actief_sinds, doel, "afgebouwd naar %.1f" % doel)

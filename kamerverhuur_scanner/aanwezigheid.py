"""Aanwezigheid + inactiviteit-setback (Fase 1: alleen het thermostaatsignaal).

Pure logica, los testbaar. Twee dingen:

1. **Interactie-detectie**: een huurder die zelf aan de thermostaat draait is
   'thuis'. Dat leiden we af uit de verwarmings-tijdreeks: het setpoint is op
   handmatig gewijzigd naar een waarde die wíj niet hebben gezet.

2. **Inactiviteit-setback-probe** (de door de gebruiker gevraagde regel): als een
   kamer `na_dagen` lang géén interactie had en de kachel staat nog op/boven de
   `drempel`, zet 'm dan één keer zacht terug naar `setback_temp` (bv. 20 -> 15).
   Krijgt de huurder het koud en draait 'm terug -> dat telt meteen als interactie
   (= thuis, en de setback wordt losgelaten). Gebeurt er niks -> waarschijnlijk
   afwezig. Zelf-corrigerend en mild; geen harde uit.

Bold (deur-signaal) komt er in Fase 2 als tweede bron bij; `status()` heeft daar
alvast een haakje voor (`bold_recent`).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

_EPS = 0.1

# Standaarden voor de setback-probe.
SETBACK_NA_DAGEN = 2
SETBACK_DREMPEL = 20.0
SETBACK_TEMP = 15.0

# Binnen hoeveel uur na een interactie noemen we iemand 'thuis'.
THUIS_UREN = 24


def detecteer_interactie(vorig_setpoint, huidig_setpoint, huidig_overlay_type, ons_commando) -> bool:
    """Of de huurder zelf de thermostaat heeft aangeraakt sinds de vorige meting.

    - alleen bij een handmatige stand (overlay), niet bij een schema-wisseling;
    - het setpoint moet gewijzigd zijn t.o.v. de vorige meting;
    - en de nieuwe waarde mag niet die zijn die wíj zelf net hebben gezet.
    """
    if huidig_overlay_type is None or huidig_setpoint is None:
        return False
    if vorig_setpoint is not None and abs(huidig_setpoint - vorig_setpoint) < _EPS:
        return False
    if ons_commando is not None and abs(huidig_setpoint - ons_commando) < _EPS:
        return False
    return True


@dataclass(frozen=True)
class SetbackRegel:
    actief: bool = False
    na_dagen: float = SETBACK_NA_DAGEN
    drempel: float = SETBACK_DREMPEL
    setback_temp: float = SETBACK_TEMP

    @staticmethod
    def uit_row(row) -> "SetbackRegel":
        def g(key, default):
            try:
                v = row[key]
            except (KeyError, IndexError, TypeError):
                v = None
            return default if v is None else v
        return SetbackRegel(
            actief=bool(g("setback_actief", 0)),
            na_dagen=float(g("setback_na_dagen", SETBACK_NA_DAGEN)),
            drempel=float(g("setback_drempel", SETBACK_DREMPEL)),
            setback_temp=float(g("setback_temp", SETBACK_TEMP)),
        )

    def geldig(self) -> bool:
        return self.na_dagen > 0 and self.setback_temp < self.drempel


@dataclass(frozen=True)
class SetbackBeslissing:
    nieuw_doel: float | None       # setpoint om te zetten (None = niets sturen)
    setback_sinds: datetime | None # nieuwe status (None = geen lopende setback)
    reden: str


def beslis_setback(regel: SetbackRegel, laatste_interactie, setback_sinds,
                   huidig_setpoint, nu: datetime) -> SetbackBeslissing:
    if not regel.actief or not regel.geldig():
        return SetbackBeslissing(None, None, "setback uit/ongeldig")
    if huidig_setpoint is None:
        return SetbackBeslissing(None, None, "kamer uit")
    if laatste_interactie is None:
        # Nog geen interactie gezien: geef de huurder het voordeel van de twijfel
        # (we gaan pas na een echte stille periode terugschakelen).
        return SetbackBeslissing(None, setback_sinds, "nog geen interactie-data")

    dagen = max(0.0, (nu - laatste_interactie).total_seconds() / 86400.0)

    if setback_sinds is None:
        # Nog niet aan het terugschakelen. Start alleen als het lang stil is én
        # de kachel nog relevant hoog staat.
        if dagen >= regel.na_dagen and huidig_setpoint >= regel.drempel - _EPS \
                and huidig_setpoint > regel.setback_temp + _EPS:
            return SetbackBeslissing(regel.setback_temp, nu,
                                     "stil %.1f dagen - setback naar %.1f" % (dagen, regel.setback_temp))
        return SetbackBeslissing(None, None, "actief genoeg of al laag")

    # Setback loopt: vasthouden (opnieuw zetten, fail-safe). De huurder die
    # terugdraait wordt als interactie herkend door de poll-laag, die de setback
    # dan loslaat (setback_sinds -> None) vóórdat we hier komen.
    return SetbackBeslissing(regel.setback_temp, setback_sinds, "setback loopt")


def status(laatste_interactie, nu: datetime, na_dagen=SETBACK_NA_DAGEN,
           onbetrouwbaar=False, bold_recent=None) -> str:
    """Schat 'thuis' / 'onzeker' / 'afwezig'.

    - bold_recent (Fase 2): True = recent een deur-activatie -> thuis. None = geen
      Bold-data (nu altijd het geval).
    - onbetrouwbaar: kamer met een fysieke tuinsleutel naast Bold, of anderszins
      onbetrouwbaar signaal -> nooit hard 'afwezig', hooguit 'onzeker'.
    """
    if bold_recent:
        return "thuis"
    if laatste_interactie is not None:
        uur = (nu - laatste_interactie).total_seconds() / 3600.0
        if uur <= THUIS_UREN:
            return "thuis"
        if not onbetrouwbaar and uur >= na_dagen * 24:
            return "afwezig"
    return "onzeker"

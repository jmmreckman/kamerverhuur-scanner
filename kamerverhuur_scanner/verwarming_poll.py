"""Orchestratie tussen de poll-service en de pure aanwezigheid-/setback-logica.

Beide providers (Tado en evohome) roepen per zone `verwerk_aanwezigheid_en_setback`
aan: die detecteert huurder-interactie, werkt de aanwezigheidsstatus bij, beslist
over de inactiviteit-setback, bewaart de status, en geeft terug welk setpoint er
eventueel gezet moet worden (de provider voert dat zelf uit).

Precedentie: staat de terugschakel-regel aan voor een zone, dan 'bezit' die het
setpoint en doet de setback niets (we tracken dan wel gewoon de aanwezigheid).
"""
from __future__ import annotations

from datetime import datetime

from . import verwarming_db as vdb
from .aanwezigheid import SetbackRegel, beslis_setback, detecteer_interactie


def _parse(ts):
    return datetime.fromisoformat(ts) if ts else None


def _stuurbaar(verwerkt) -> bool:
    s = verwerkt.get("stuurbaar")
    if s is not None:
        return bool(s)                       # evohome zet dit expliciet
    return verwerkt.get("online") is not False  # Tado: niet sturen op offline


def verwerk_aanwezigheid_en_setback(conn, provider, home_id, zone_id,
                                    vorige_setpoint, verwerkt, zc, nu) -> float | None:
    """Retourneert het setpoint dat de provider moet zetten (setback), of None."""
    aanw = vdb.lees_aanwezigheid(conn, provider, home_id, zone_id)
    laatste_interactie = _parse(aanw["laatste_interactie"]) if aanw else None
    setback_sinds = _parse(aanw["setback_sinds"]) if aanw else None
    ons_commando = aanw["setback_doel"] if aanw else None

    # Een lopend terugschakel-commando telt óók als 'van ons' (niet als interactie).
    ts = vdb.lees_terugschakeling(conn, provider, home_id, zone_id)
    if ts and ts["laatste_doel"] is not None:
        ons_commando = ts["laatste_doel"]

    if detecteer_interactie(vorige_setpoint, verwerkt.get("setpoint"),
                            verwerkt.get("overlay_type"), ons_commando):
        laatste_interactie = nu
        setback_sinds = None                 # huurder is thuis -> lopende setback loslaten

    nieuw_doel = None
    if zc is not None and zc["regel_actief"]:
        setback_sinds = None                 # terugschakel bezit het setpoint
    else:
        regel = SetbackRegel.uit_row(zc) if zc is not None else SetbackRegel()
        besluit = beslis_setback(regel, laatste_interactie, setback_sinds,
                                 verwerkt.get("setpoint"), nu)
        setback_sinds = besluit.setback_sinds
        nieuw_doel = besluit.nieuw_doel

    vdb.schrijf_aanwezigheid(
        conn, provider, home_id, zone_id,
        laatste_interactie.isoformat() if laatste_interactie else None,
        setback_sinds.isoformat() if setback_sinds else None,
        nieuw_doel,
    )

    if nieuw_doel is not None and _stuurbaar(verwerkt):
        return nieuw_doel
    return None

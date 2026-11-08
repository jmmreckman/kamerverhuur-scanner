"""Evohome-client (Honeywell/Resideo Total Connect Comfort) als tweede provider
naast Tado. Wikkelt de async library `evohome-async` (1.0.6, 3.12-compatibel)
in een synchrone laag die de poll-service kan aanroepen.

De pure verwerking (`verwerk_zone`) staat los en is testbaar zonder netwerk. De
netwerk-/async-delen zitten in `draai_ronde()` - die doet in één keer: inloggen
(token hergebruikt tegen de rate-limit), alle locaties uitlezen (behalve
overgeslagen locaties, bv. een verkocht pand), per zone een meting opslaan, en -
alleen als er voor een zone een regel 'actief' staat - de terugschakeling
toepassen.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from . import verwarming_db as vdb, verwarming_poll
from .verwarming_regels import Regel, beslis, sensor_ok

logger = logging.getLogger(__name__)

PROVIDER = "evohome"
_SETBACK_HOLD_MIN = 45


# --- pure verwerking (los testbaar) -----------------------------------------

def _fault_type(f):
    if isinstance(f, dict):
        return f.get("faultType") or f.get("fault_type") or f.get("type")
    return getattr(f, "fault_type", None) or getattr(f, "faultType", None)


def verwerk_zone(temperature, target, mode, active_faults) -> dict:
    """Zet de ruwe zone-velden om naar dezelfde vorm als tado_client.verwerk_state.

    online: een zone met een 'CommunicationLost'-storing (of zonder temperatuur)
    is offline/bevroren - niet op sturen, niet meetellen. LowBattery alleen is
    een waarschuwing, geen offline.
    """
    fault_types = [str(_fault_type(f)) for f in (active_faults or []) if _fault_type(f)]
    # Twee soorten storing: de SENSOR kwijt -> temperatuur onbetrouwbaar -> offline;
    # alleen de ACTUATOR (kraan) kwijt -> meting klopt nog, maar niet aanstuurbaar.
    sensor_lost = any("SensorCommunicationLost" in ft for ft in fault_types)
    actuator_lost = any("ActuatorCommunicationLost" in ft for ft in fault_types)
    online = (temperature is not None) and not sensor_lost
    stuurbaar = online and not actuator_lost

    mode_str = str(mode or "")
    if "FollowSchedule" in mode_str:
        overlay_type = None
    elif "Temporary" in mode_str:
        overlay_type = "TIMER"
    elif "Permanent" in mode_str:
        overlay_type = "MANUAL"
    else:
        overlay_type = "MANUAL" if target is not None else None

    return {
        "inside": temperature,
        "humidity": None,             # evohome/Honeywell geeft geen luchtvochtigheid per zone
        "setpoint": target,
        "power": "ON" if target is not None else None,
        "heating_pct": None,          # evohome geeft geen stookvermogen per zone
        "overlay_type": overlay_type,
        "online": online,
        "stuurbaar": stuurbaar,
        "faults": fault_types,
    }


def _skip_sets(config):
    ruw = [s.strip() for s in (getattr(config, "evohome_skip_locaties", "") or "").split(",") if s.strip()]
    return {s.lower() for s in ruw}


def is_geconfigureerd(config) -> bool:
    return bool(getattr(config, "evohome_username", None) and getattr(config, "evohome_password", None))


# --- token-manager met bestand-persistentie ---------------------------------

def _maak_token_manager(config, session):
    from evohomeasync2 import AbstractTokenManager

    token_file = config.evohome_token_pad()

    class FileTokenManager(AbstractTokenManager):
        async def save_access_token(self) -> None:
            data = {
                "access_token": self._access_token,
                "access_token_expires": self._access_token_expires.isoformat(),
                "refresh_token": self._refresh_token,
            }
            os.makedirs(os.path.dirname(token_file) or ".", exist_ok=True)
            with open(token_file, "w") as f:
                json.dump(data, f)
            try:
                os.chmod(token_file, 0o600)
            except OSError:
                pass

    tm = FileTokenManager(config.evohome_username, config.evohome_password, session)
    # eerder bewaard token hergebruiken (scheelt een login -> rate-limit)
    try:
        with open(token_file) as f:
            d = json.load(f)
        tm._access_token = d["access_token"]
        tm._access_token_expires = datetime.fromisoformat(d["access_token_expires"])
        tm._refresh_token = d.get("refresh_token", "")
    except (OSError, ValueError, KeyError):
        pass
    return tm


# --- één ronde (inloggen + uitlezen + eventueel sturen) ---------------------

async def _ronde_async(config, conn) -> int:
    import aiohttp
    from evohomeasync2 import EvohomeClient

    skip = _skip_sets(config)
    aantal = 0
    async with aiohttp.ClientSession() as session:
        tm = _maak_token_manager(config, session)
        client = EvohomeClient(tm, websession=session)
        await client.update()
        for loc in client.locations:
            if str(loc.id).lower() in skip or str(loc.name or "").lower() in skip:
                logger.info("[evohome] Locatie %s overgeslagen (op de overslaan-lijst).", loc.name)
                continue
            for gwy in loc.gateways:
                for tcs in gwy.systems:
                    for z in tcs.zones:
                        v = verwerk_zone(z.temperature, z.target_heat_temperature,
                                         z.mode, z.active_faults)
                        vdb.registreer_zone(conn, PROVIDER, loc.id, loc.name, z.id, z.name, None)
                        vorige = vdb.laatste_sample(conn, PROVIDER, loc.id, z.id)
                        vorig_setpoint = vorige["setpoint"] if vorige else None
                        vdb.bewaar_sample(conn, PROVIDER, loc.id, z.id,
                                          inside=v["inside"], setpoint=v["setpoint"],
                                          power=v["power"], heating_pct=v["heating_pct"],
                                          overlay_type=v["overlay_type"], online=v["online"],
                                          humidity=v.get("humidity"))
                        aantal += 1
                        zc = vdb.zone(conn, PROVIDER, loc.id, z.id)
                        nu = datetime.now(timezone.utc)
                        try:
                            setback_doel = verwarming_poll.verwerk_aanwezigheid_en_setback(
                                conn, PROVIDER, loc.id, z.id, vorig_setpoint, v, zc, nu)
                            if setback_doel is not None:
                                tot = nu + timedelta(minutes=_SETBACK_HOLD_MIN)
                                await z.set_temperature(setback_doel, until=tot)
                                logger.info("[evohome %s] Setback (afwezig) -> %.1f", z.id, setback_doel)
                        except Exception:
                            logger.exception("[evohome %s] Aanwezigheid/setback mislukt.", z.id)
                        if zc and zc["regel_actief"]:
                            try:
                                await _pas_regel_toe(conn, loc.id, z, v)
                            except Exception:
                                logger.exception("[evohome %s] Regel toepassen mislukt.", z.id)
    return aantal


async def _pas_regel_toe(conn, home_id, zone, verwerkt) -> None:
    if not verwerkt.get("stuurbaar"):
        logger.info("[evohome %s] Zone niet-stuurbaar (offline/kraan-storing) - niet sturen.", zone.id)
        return
    if not sensor_ok(verwerkt.get("inside")):
        return
    regel = Regel.uit_row(zone_config_row(conn, home_id, zone.id))
    st = vdb.lees_terugschakeling(conn, PROVIDER, home_id, zone.id)
    actief_sinds = datetime.fromisoformat(st["actief_sinds"]) if st and st["actief_sinds"] else None
    laatste_doel = st["laatste_doel"] if st else None
    nu = datetime.now(timezone.utc)
    besluit = beslis(regel, verwerkt.get("setpoint"), nu, actief_sinds, laatste_doel)
    if besluit.actief_sinds is None:
        vdb.wis_terugschakeling(conn, PROVIDER, home_id, zone.id)
    else:
        vdb.schrijf_terugschakeling(conn, PROVIDER, home_id, zone.id,
                                    besluit.actief_sinds.isoformat(), besluit.laatste_doel)
        if besluit.laatste_doel is not None:
            # temporary override tot ruim na het poll-interval (fail-safe: valt
            # vanzelf terug op het schema als de service stilvalt).
            tot = datetime.now(timezone.utc) + timedelta(minutes=max(regel.interval_min, 10) * 3)
            await zone.set_temperature(besluit.laatste_doel, until=tot)
            logger.info("[evohome %s] Terugschakeling -> %.1f", zone.id, besluit.laatste_doel)


def zone_config_row(conn, home_id, zone_id):
    return vdb.zone(conn, PROVIDER, home_id, zone_id)


def draai_ronde(config, conn) -> int:
    """Synchroon aanroepbaar vanuit de poll-service: doet één evohome-ronde en
    geeft het aantal uitgelezen zones terug."""
    return asyncio.run(_ronde_async(config, conn))

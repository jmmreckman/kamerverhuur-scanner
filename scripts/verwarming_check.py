#!/usr/bin/env python3
"""Verwarming-check: leest elk kwartier alle Tado-zones uit en bewaart ze als
tijdreeks (monitoring). Staat voor een zone een terugschakel-regel 'actief'
aan, dan past hij die ook toe (vriendelijk afbouwen via een overlay) - anders
puur monitoren, zonder iets te sturen.

Zelfde patroon als scripts/dagelijkse_controle.py: dit proces blijft zelf
draaien, wacht tot het volgende kwartier, doet een ronde, en wacht weer. Geen
losse cron nodig. Zonder ingelogd Tado-account (zie scripts/verwarming_login.py)
doet de service niets - hij slaapt en probeert het later opnieuw.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from kamerverhuur_scanner import evohome_client, tado_client, verwarming_db as vdb
from kamerverhuur_scanner.config import Config, ConfigError
from kamerverhuur_scanner.tado_client import PROVIDER, TadoError, TadoClient
from kamerverhuur_scanner.verwarming_regels import Regel, beslis, sensor_ok

_TIJDZONE = ZoneInfo("Europe/Amsterdam")
_KWARTIER_MIN = 15
_RETENTIE_DAGEN = 120

logger = logging.getLogger(__name__)


def _seconden_tot_volgend_kwartier(nu: datetime | None = None) -> float:
    nu = nu or datetime.now(_TIJDZONE)
    minuut = (nu.minute // _KWARTIER_MIN + 1) * _KWARTIER_MIN
    volgende = nu.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=minuut)
    return max(5.0, (volgende - nu).total_seconds())


def _serial(zone: dict):
    for d in zone.get("devices", []) or []:
        s = d.get("serialNo") or d.get("shortSerialNo")
        if s:
            return s
    return None


def _pas_regel_toe(conn, client: TadoClient, home_id, zone_id, zc, verwerkt) -> None:
    """Past de terugschakel-regel toe voor één zone (alleen als 'actief')."""
    if verwerkt.get("online") is False:
        logger.info("[%s/%s] Knop offline - niet sturen (meting is verouderd).", home_id, zone_id)
        return
    if not sensor_ok(verwerkt.get("inside")):
        logger.info("[%s/%s] Sensorwaarde onbetrouwbaar (%.1f?) - niet sturen.",
                    home_id, zone_id, verwerkt.get("inside") or -1)
        return
    regel = Regel.uit_row(zc)
    st = vdb.lees_terugschakeling(conn, PROVIDER, home_id, zone_id)
    actief_sinds = None
    laatste_doel = None
    if st and st["actief_sinds"]:
        actief_sinds = datetime.fromisoformat(st["actief_sinds"])
        laatste_doel = st["laatste_doel"]
    nu = datetime.now(timezone.utc)
    besluit = beslis(regel, verwerkt.get("setpoint"), nu, actief_sinds, laatste_doel)

    if besluit.actief_sinds is None:
        vdb.wis_terugschakeling(conn, PROVIDER, home_id, zone_id)
    else:
        vdb.schrijf_terugschakeling(conn, PROVIDER, home_id, zone_id,
                                    besluit.actief_sinds.isoformat(), besluit.laatste_doel)
        # Houd de overlay actief met een TIMER die ruim langer is dan het
        # poll-interval: valt vanzelf terug op het schema als de service ooit
        # stilvalt (fail-safe, de knop blijft dan gewoon werken).
        if besluit.laatste_doel is not None:
            duur = max(regel.interval_min, 10) * 3 * 60
            try:
                client.set_overlay(home_id, zone_id, besluit.laatste_doel, duur_seconden=duur)
                logger.info("[%s/%s] Terugschakeling: %s -> doel %.1f",
                            home_id, zone_id, besluit.reden, besluit.laatste_doel)
            except TadoError:
                logger.exception("[%s/%s] Overlay zetten mislukt.", home_id, zone_id)


def _draai_een_ronde(config: Config, client: TadoClient) -> None:
    conn = vdb.verbind(vdb.pad(config.state_dir))
    try:
        homes = client.get_homes()
    except TadoError:
        logger.exception("Kon Tado-huizen niet ophalen.")
        conn.close()
        return
    for home in homes:
        home_id = home.get("id")
        home_naam = home.get("name")
        try:
            zones = client.get_zones(home_id)
        except TadoError:
            logger.exception("[home %s] Zones ophalen mislukt.", home_id)
            continue
        for z in zones:
            if z.get("type") != "HEATING":
                continue
            zone_id = z.get("id")
            vdb.registreer_zone(conn, PROVIDER, home_id, home_naam, zone_id,
                                z.get("name"), _serial(z))
            try:
                state = client.get_state(home_id, zone_id)
            except TadoError:
                logger.exception("[%s/%s] State ophalen mislukt.", home_id, zone_id)
                continue
            v = tado_client.verwerk_state(state)
            vdb.bewaar_sample(conn, PROVIDER, home_id, zone_id,
                              inside=v["inside"], setpoint=v["setpoint"], power=v["power"],
                              heating_pct=v["heating_pct"], overlay_type=v["overlay_type"],
                              online=v["online"])
            zc = vdb.zone(conn, PROVIDER, home_id, zone_id)
            if zc and zc["regel_actief"]:
                try:
                    _pas_regel_toe(conn, client, home_id, zone_id, zc, v)
                except Exception:
                    logger.exception("[%s/%s] Regel toepassen mislukt.", home_id, zone_id)
    verwijderd = vdb.prune_samples(conn, _RETENTIE_DAGEN)
    if verwijderd:
        logger.info("Oude metingen opgeruimd: %d rijen.", verwijderd)
    conn.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_dotenv()
    try:
        config = Config.load()
    except ConfigError as exc:
        logger.error("Configuratiefout: %s", exc)
        raise SystemExit(1)

    client = TadoClient(config.tado_token_pad())

    while True:
        if not client.is_ingelogd():
            logger.info("Nog niet ingelogd bij Tado (geen token). "
                        "Draai scripts/verwarming_login.py. Opnieuw proberen over een kwartier.")
        else:
            try:
                _draai_een_ronde(config, client)
            except Exception:
                logger.exception("Tado-ronde mislukt - volgende kwartier opnieuw.")

        # Evohome (tweede provider) - alleen als TCC-inlog is ingesteld.
        if evohome_client.is_geconfigureerd(config):
            conn = vdb.verbind(vdb.pad(config.state_dir))
            try:
                aantal = evohome_client.draai_ronde(config, conn)
                logger.info("[evohome] %d zones uitgelezen.", aantal)
            except Exception:
                logger.exception("Evohome-ronde mislukt - volgende kwartier opnieuw.")
            finally:
                conn.close()

        wacht = _seconden_tot_volgend_kwartier()
        logger.info("Volgende uitlezing over %.0f minuten.", wacht / 60)
        time.sleep(wacht)


if __name__ == "__main__":
    main()

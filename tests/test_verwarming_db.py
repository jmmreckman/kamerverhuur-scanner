"""Tests voor de pure SQLite-opslaglaag van de verwarmingsmodule."""
from __future__ import annotations

import os
import tempfile

from kamerverhuur_scanner import verwarming_db as vdb


def _verbind():
    tmp = tempfile.mkdtemp()
    return vdb.verbind(os.path.join(tmp, "verwarming.db"))


def test_registreer_zone_bewaart_koppeling_en_regel_bij_herontdekken():
    conn = _verbind()
    vdb.registreer_zone(conn, "tado", 111, "Mijn Huis", 3, "Slaapkamer", "VA123")
    # gebruiker koppelt + zet regel
    vdb.zet_koppeling(conn, "tado", 111, 3, "mijnpand", "Kamer 1")
    vdb.zet_regel(conn, "tado", 111, 3, regel_actief=True, max_temp=25, stap=1,
                  interval_min=15, vloer_temp=20, na_uren=3, nacht_temp=18)
    # poll ontdekt de zone opnieuw (naam gewijzigd) -> koppeling/regel blijven
    vdb.registreer_zone(conn, "tado", 111, "Mijn Huis", 3, "Slaapkamer (nieuw)", None)
    z = vdb.zone(conn, "tado", 111, 3)
    assert z["zone_naam"] == "Slaapkamer (nieuw)"
    assert z["device_serial"] == "VA123"  # niet overschreven met None
    assert z["pand_slug"] == "mijnpand"
    assert z["kamer"] == "Kamer 1"
    assert z["regel_actief"] == 1
    assert z["max_temp"] == 25


def test_lijst_zones_filtert_op_pand():
    conn = _verbind()
    vdb.registreer_zone(conn, "tado", 111, "H", 1, "A")
    vdb.registreer_zone(conn, "tado", 111, "H", 2, "B")
    vdb.zet_koppeling(conn, "tado", 111, 1, "pandx", "K1")
    # pandx: alleen zone 1
    assert {z["zone_id"] for z in vdb.lijst_zones(conn, "pandx")} == {1}
    # inclusief ongekoppeld: zone 1 (pandx) + zone 2 (nog los)
    assert {z["zone_id"] for z in vdb.lijst_zones(conn, "pandx", inclusief_ongekoppeld=True)} == {1, 2}
    # geen filter: alles
    assert {z["zone_id"] for z in vdb.lijst_zones(conn)} == {1, 2}


def test_samples_en_conclusies():
    conn = _verbind()
    vdb.registreer_zone(conn, "tado", 1, "H", 5, "Zolder")
    for i, (sp, binnen) in enumerate([(19, 19.0), (25, 24.0), (25, 24.5), (21, 20.0)]):
        vdb.bewaar_sample(conn, "tado", 1, 5, inside=binnen, setpoint=sp, power="ON",
                          heating_pct=0.0, overlay_type="MANUAL",
                          ts="2026-11-07T0%d:00:00+00:00" % i)
    laatste = vdb.laatste_sample(conn, "tado", 1, 5)
    assert laatste["setpoint"] == 21
    hist = vdb.historie(conn, "tado", 1, 5)
    assert [h["setpoint"] for h in hist] == [19, 25, 25, 21]  # oplopend in tijd
    c = vdb.conclusies(conn, "tado", 1, 5, drempel=22.0)
    assert c["aantal"] == 4
    assert c["max_setpoint"] == 25
    assert c["aandeel_boven"] == 50  # 2 van 4 metingen >= 22


def test_prune_verwijdert_oude_samples():
    conn = _verbind()
    vdb.registreer_zone(conn, "tado", 1, "H", 5, "Z")
    vdb.bewaar_sample(conn, "tado", 1, 5, inside=20.0, setpoint=20, power="ON",
                      heating_pct=0.0, overlay_type=None, ts="2000-01-01T00:00:00+00:00")
    vdb.bewaar_sample(conn, "tado", 1, 5, inside=20.0, setpoint=20, power="ON",
                      heating_pct=0.0, overlay_type=None)  # nu
    verwijderd = vdb.prune_samples(conn, ouder_dan_dagen=120)
    assert verwijderd == 1
    assert len(vdb.historie(conn, "tado", 1, 5)) == 1


def test_terugschakel_status_schrijven_lezen_wissen():
    conn = _verbind()
    assert vdb.lees_terugschakeling(conn, "tado", 1, 5) is None
    vdb.schrijf_terugschakeling(conn, "tado", 1, 5, "2026-11-07T10:00:00+00:00", 24.0)
    r = vdb.lees_terugschakeling(conn, "tado", 1, 5)
    assert r["laatste_doel"] == 24.0
    vdb.schrijf_terugschakeling(conn, "tado", 1, 5, "2026-11-07T10:00:00+00:00", 23.0)  # upsert
    assert vdb.lees_terugschakeling(conn, "tado", 1, 5)["laatste_doel"] == 23.0
    vdb.wis_terugschakeling(conn, "tado", 1, 5)
    assert vdb.lees_terugschakeling(conn, "tado", 1, 5) is None

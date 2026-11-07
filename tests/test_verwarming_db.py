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


def test_conclusies_negeert_offline_metingen():
    conn = _verbind()
    vdb.registreer_zone(conn, "tado", 1, "H", 5, "BG straat")
    # drie normale metingen rond 20-21, plus een bevroren offline-meting van 31.4
    for i, sp in enumerate([20, 21, 20]):
        vdb.bewaar_sample(conn, "tado", 1, 5, inside=float(sp), setpoint=sp, power="ON",
                          heating_pct=0.0, overlay_type=None, online=True,
                          ts="2026-11-07T0%d:00:00+00:00" % i)
    vdb.bewaar_sample(conn, "tado", 1, 5, inside=31.4, setpoint=19, power="ON",
                      heating_pct=0.0, overlay_type="MANUAL", online=False,
                      ts="2026-11-07T09:00:00+00:00")
    c = vdb.conclusies(conn, "tado", 1, 5)
    assert c["aantal"] == 3                 # offline-meting telt niet mee
    assert c["max_setpoint"] == 21          # niet de bevroren 19/31.4-regel
    assert c["gem_binnen"] and c["gem_binnen"] < 22   # niet opgeblazen door 31.4


def test_online_wordt_opgeslagen_als_0_1_null():
    conn = _verbind()
    vdb.registreer_zone(conn, "tado", 1, "H", 5, "Z")
    vdb.bewaar_sample(conn, "tado", 1, 5, inside=20.0, setpoint=20, power="ON",
                      heating_pct=0.0, overlay_type=None, online=False)
    assert vdb.laatste_sample(conn, "tado", 1, 5)["online"] == 0
    vdb.bewaar_sample(conn, "tado", 1, 5, inside=20.0, setpoint=20, power="ON",
                      heating_pct=0.0, overlay_type=None, online=None)
    assert vdb.laatste_sample(conn, "tado", 1, 5)["online"] is None


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


def test_migratie_voegt_online_kolom_toe_aan_oude_db():
    import sqlite3
    tmp = tempfile.mkdtemp()
    pad = os.path.join(tmp, "verwarming.db")
    # oude sample-tabel zonder 'online'-kolom
    oud = sqlite3.connect(pad)
    oud.execute("CREATE TABLE sample (provider TEXT, home_id TEXT, zone_id INTEGER, ts TEXT,"
                " inside REAL, setpoint REAL, power TEXT, heating_pct REAL, overlay_type TEXT)")
    oud.commit(); oud.close()
    # verbind() moet de kolom toevoegen en daarna gewoon werken
    conn = vdb.verbind(pad)
    kolommen = [r[1] for r in conn.execute("PRAGMA table_info(sample)").fetchall()]
    assert "online" in kolommen
    vdb.registreer_zone(conn, "tado", 1, "H", 5, "Z")
    vdb.bewaar_sample(conn, "tado", 1, 5, inside=20.0, setpoint=20, power="ON",
                      heating_pct=0.0, overlay_type=None, online=True)
    assert vdb.laatste_sample(conn, "tado", 1, 5)["online"] == 1


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

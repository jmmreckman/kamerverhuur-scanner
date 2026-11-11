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


def test_humidity_opslag_en_in_conclusies():
    conn = _verbind()
    vdb.registreer_zone(conn, "tado", 1, "H", 5, "Z")
    vdb.bewaar_sample(conn, "tado", 1, 5, inside=20.0, setpoint=20, power="ON",
                      heating_pct=0.0, overlay_type=None, online=True, humidity=58.0,
                      ts="2026-11-07T10:00:00+00:00")
    vdb.bewaar_sample(conn, "tado", 1, 5, inside=20.0, setpoint=20, power="ON",
                      heating_pct=0.0, overlay_type=None, online=True, humidity=62.0,
                      ts="2026-11-07T11:00:00+00:00")
    assert vdb.laatste_sample(conn, "tado", 1, 5)["humidity"] == 62.0
    c = vdb.conclusies(conn, "tado", 1, 5)
    assert c["gem_vocht"] == 60 and c["max_vocht"] == 62
    # evohome-achtige zone zonder vocht -> gem_vocht None (geen crash)
    vdb.registreer_zone(conn, "evohome", 9, "H2", 1, "Studio")
    vdb.bewaar_sample(conn, "evohome", 9, 1, inside=19.0, setpoint=19, power="ON",
                      heating_pct=None, overlay_type=None, online=True)
    assert vdb.conclusies(conn, "evohome", 9, 1)["gem_vocht"] is None


def test_lang_warme_zones_signaal():
    conn = _verbind()
    # kamer A: al dagen warm (23-24), geen regel -> moet getriggerd worden
    vdb.registreer_zone(conn, "tado", 1, "H", 1, "Kamer A")
    vdb.zet_koppeling(conn, "tado", 1, 1, "pandx", "Kamer A")
    # kamer B: warm maar heeft al een terugschakel-regel -> niet triggeren
    vdb.registreer_zone(conn, "tado", 1, "H", 2, "Kamer B")
    vdb.zet_koppeling(conn, "tado", 1, 2, "pandx", "Kamer B")
    vdb.zet_regel(conn, "tado", 1, 2, regel_actief=True, max_temp=25, stap=1,
                  interval_min=15, vloer_temp=20, na_uren=3, nacht_temp=18)
    # kamer C: koel -> niet triggeren
    vdb.registreer_zone(conn, "tado", 1, "H", 3, "Kamer C")
    vdb.zet_koppeling(conn, "tado", 1, 3, "pandx", "Kamer C")
    # metingen over ~3 dagen (elke 12 uur eentje)
    for u in range(0, 72, 12):
        ts = "2026-11-%02dT%02d:00:00+00:00" % (1 + u // 24, u % 24)
        vdb.bewaar_sample(conn, "tado", 1, 1, inside=23.5, setpoint=24, power="ON", heating_pct=0, overlay_type="MANUAL", online=True, ts=ts)
        vdb.bewaar_sample(conn, "tado", 1, 2, inside=24.0, setpoint=24, power="ON", heating_pct=0, overlay_type="MANUAL", online=True, ts=ts)
        vdb.bewaar_sample(conn, "tado", 1, 3, inside=19.0, setpoint=19, power="ON", heating_pct=0, overlay_type=None, online=True, ts=ts)
    sinds = "2026-10-30T00:00:00+00:00"   # ruim venster
    span = "2026-11-10T00:00:00+00:00"    # data moet vóór dit moment beginnen (alles)
    warm = vdb.lang_warme_zones(conn, "pandx", sinds, span, drempel=22.0, min_n=3)
    zone_ids = {r["z"] for r in warm}
    assert zone_ids == {1}                 # alleen Kamer A (B heeft regel, C is koel)


def test_vochtige_zones_schimmel_signaal():
    conn = _verbind()
    # kamer A: aanhoudend vochtig (72-75%) -> moet triggeren
    vdb.registreer_zone(conn, "tado", 1, "H", 1, "Kamer A")
    vdb.zet_koppeling(conn, "tado", 1, 1, "pandx", "Kamer A")
    # kamer B: droog (45%) -> niet triggeren
    vdb.registreer_zone(conn, "tado", 1, "H", 2, "Kamer B")
    vdb.zet_koppeling(conn, "tado", 1, 2, "pandx", "Kamer B")
    # kamer C (evohome): geen vochtmeting -> nooit triggeren
    vdb.registreer_zone(conn, "evohome", 9, "H2", 3, "Studio")
    vdb.zet_koppeling(conn, "evohome", 9, 3, "pandx", "Studio")
    for u in range(0, 72, 12):
        ts = "2026-11-%02dT%02d:00:00+00:00" % (1 + u // 24, u % 24)
        vdb.bewaar_sample(conn, "tado", 1, 1, inside=20, setpoint=20, power="ON",
                          heating_pct=0, overlay_type=None, online=True, humidity=73.0, ts=ts)
        vdb.bewaar_sample(conn, "tado", 1, 2, inside=20, setpoint=20, power="ON",
                          heating_pct=0, overlay_type=None, online=True, humidity=45.0, ts=ts)
        vdb.bewaar_sample(conn, "evohome", 9, 3, inside=20, setpoint=20, power="ON",
                          heating_pct=None, overlay_type=None, online=True, ts=ts)
    sinds = "2026-10-30T00:00:00+00:00"
    span = "2026-11-10T00:00:00+00:00"
    vochtig = vdb.vochtige_zones(conn, "pandx", sinds, span, drempel=70.0, min_n=3)
    assert {r["z"] for r in vochtig} == {1}      # alleen Kamer A
    assert round(vochtig[0]["gem"]) == 73


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
    assert "humidity" in kolommen          # ook de later toegevoegde vocht-kolom
    vdb.registreer_zone(conn, "tado", 1, "H", 5, "Z")
    vdb.bewaar_sample(conn, "tado", 1, 5, inside=20.0, setpoint=20, power="ON",
                      heating_pct=0.0, overlay_type=None, online=True)
    assert vdb.laatste_sample(conn, "tado", 1, 5)["online"] == 1


def test_setback_regel_en_aanwezigheid():
    conn = _verbind()
    vdb.registreer_zone(conn, "tado", 1, "H", 5, "Kamer")
    vdb.zet_setback_regel(conn, "tado", 1, 5, setback_actief=True, na_dagen=2,
                          drempel=20, setback_temp=15)
    z = vdb.zone(conn, "tado", 1, 5)
    assert z["setback_actief"] == 1 and z["setback_drempel"] == 20 and z["setback_temp"] == 15
    # aanwezigheid upsert
    assert vdb.lees_aanwezigheid(conn, "tado", 1, 5) is None
    vdb.schrijf_aanwezigheid(conn, "tado", 1, 5, "2026-11-08T10:00:00+00:00", None, None)
    assert vdb.lees_aanwezigheid(conn, "tado", 1, 5)["laatste_interactie"].startswith("2026-11-08")
    vdb.schrijf_aanwezigheid(conn, "tado", 1, 5, "2026-11-08T10:00:00+00:00",
                             "2026-11-08T11:00:00+00:00", 15.0)
    r = vdb.lees_aanwezigheid(conn, "tado", 1, 5)
    assert r["setback_sinds"].startswith("2026-11-08T11") and r["setback_doel"] == 15.0


def test_migratie_voegt_setback_kolommen_toe_aan_oude_zone_config():
    import sqlite3
    tmp = tempfile.mkdtemp()
    pad = os.path.join(tmp, "verwarming.db")
    oud = sqlite3.connect(pad)
    # oude zone_config zoals vóór de setback-kolommen (wel home_naam/device_serial/etc.)
    oud.execute("CREATE TABLE zone_config (provider TEXT, home_id TEXT, home_naam TEXT,"
                " zone_id INTEGER, zone_naam TEXT, device_serial TEXT, laatst_gezien TEXT,"
                " pand_slug TEXT, kamer TEXT, regel_actief INTEGER,"
                " PRIMARY KEY (provider, home_id, zone_id))")
    oud.commit(); oud.close()
    conn = vdb.verbind(pad)
    kol = [r[1] for r in conn.execute("PRAGMA table_info(zone_config)").fetchall()]
    assert "setback_actief" in kol and "setback_temp" in kol
    vdb.registreer_zone(conn, "tado", 1, "H", 5, "Z")
    vdb.zet_setback_regel(conn, "tado", 1, 5, setback_actief=True, na_dagen=2, drempel=20, setback_temp=15)
    assert vdb.zone(conn, "tado", 1, 5)["setback_actief"] == 1


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

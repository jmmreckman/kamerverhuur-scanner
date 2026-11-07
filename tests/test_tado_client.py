"""Tests voor de pure delen van de Tado-client (parsing + token-opslag)."""
from __future__ import annotations

import os
import tempfile

from kamerverhuur_scanner import tado_client as tc


def test_verwerk_state_handmatig():
    state = {
        "setting": {"type": "HEATING", "power": "ON", "temperature": {"celsius": 24.0}},
        "sensorDataPoints": {"insideTemperature": {"celsius": 24.97}},
        "activityDataPoints": {"heatingPower": {"percentage": 30.0}},
        "overlay": {"termination": {"type": "TIMER", "remainingTimeInSeconds": 120}},
        "link": {"state": "ONLINE"},
    }
    r = tc.verwerk_state(state)
    assert r == {"inside": 24.97, "setpoint": 24.0, "power": "ON",
                 "heating_pct": 30.0, "overlay_type": "TIMER", "online": True}


def test_verwerk_state_offline_knop():
    # Offline knop: Tado geeft nog de bevroren meting + setpoint, maar link=OFFLINE.
    state = {
        "setting": {"type": "HEATING", "power": "ON", "temperature": {"celsius": 19.0}},
        "sensorDataPoints": {"insideTemperature": {"celsius": 31.4}},
        "link": {"state": "OFFLINE"},
    }
    r = tc.verwerk_state(state)
    assert r["online"] is False
    assert r["setpoint"] == 19.0 and r["inside"] == 31.4


def test_verwerk_state_zonder_link_is_online_onbekend():
    assert tc.verwerk_state({})["online"] is None


def test_verwerk_state_uit_en_op_schema():
    state = {
        "setting": {"type": "HEATING", "power": "OFF"},
        "sensorDataPoints": {"insideTemperature": {"celsius": 16.1}},
        "activityDataPoints": {"heatingPower": {"percentage": 0.0}},
        "overlay": None,
    }
    r = tc.verwerk_state(state)
    assert r["setpoint"] is None        # power OFF -> geen temperatuur
    assert r["power"] == "OFF"
    assert r["overlay_type"] is None    # geen overlay -> op schema


def test_verwerk_state_lege_velden_niet_crashen():
    assert tc.verwerk_state({})["inside"] is None


def test_token_schrijven_en_lezen_roundtrip():
    tmp = tempfile.mkdtemp()
    pad = os.path.join(tmp, "sub", "tado_token.json")
    assert tc._lees_token(pad) is None
    tc._schrijf_token(pad, "refresh-abc")
    assert tc._lees_token(pad) == "refresh-abc"
    # bestand is alleen voor de eigenaar leesbaar
    assert (os.stat(pad).st_mode & 0o077) == 0

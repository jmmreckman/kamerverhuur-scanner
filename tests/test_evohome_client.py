"""Tests voor de pure verwerking van de evohome-client (zonder netwerk)."""
from __future__ import annotations

from kamerverhuur_scanner.evohome_client import verwerk_zone


class _Fault:
    def __init__(self, t):
        self.fault_type = t


def test_normale_online_zone():
    v = verwerk_zone(20.0, 21.0, "FollowSchedule", [])
    assert v["online"] is True
    assert v["setpoint"] == 21.0 and v["inside"] == 20.0
    assert v["power"] == "ON"
    assert v["overlay_type"] is None       # volgt schema


def test_communicatiestoring_is_offline():
    v = verwerk_zone(19.0, 19.0, "FollowSchedule", [{"faultType": "TempZoneActuatorCommunicationLost"}])
    assert v["online"] is False
    assert "TempZoneActuatorCommunicationLost" in v["faults"]


def test_geen_temperatuur_is_offline():
    assert verwerk_zone(None, 19.0, "FollowSchedule", [])["online"] is False


def test_lege_batterij_is_waarschuwing_geen_offline():
    v = verwerk_zone(18.0, 20.0, "FollowSchedule", [{"faultType": "TempZoneSensorLowBattery"}])
    assert v["online"] is True              # meet nog, dus niet offline
    assert v["faults"] == ["TempZoneSensorLowBattery"]


def test_overlay_type_uit_modus():
    assert verwerk_zone(20, 22, "TemporaryOverride", [])["overlay_type"] == "TIMER"
    assert verwerk_zone(20, 22, "PermanentOverride", [])["overlay_type"] == "MANUAL"


def test_fault_als_object_wordt_ook_herkend():
    v = verwerk_zone(19.0, 19.0, "FollowSchedule", [_Fault("TempZoneSensorCommunicationLost")])
    assert v["online"] is False
    assert v["faults"] == ["TempZoneSensorCommunicationLost"]

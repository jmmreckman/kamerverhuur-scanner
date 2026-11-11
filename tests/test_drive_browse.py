"""Tests voor het doorbladeren van de automatisch aangemaakte "Steenhub
<pandnaam>"-Drive-map via rclone (drive_browse.py) - rclone zelf wordt hier
nooit echt aangeroepen, alleen een nep-subprocess.run()."""
import json
import subprocess
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from kamerverhuur_scanner import drive_browse
from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.drive_browse import DriveBrowseError
from kamerverhuur_scanner.models import Pand

PAND = Pand(
    slug="mahoniestraat", naam="Mahoniestraat 15", google_sheet_id="x", google_sheet_worksheet="Huurders",
    history_worksheet="Historie", bunq_rekening_iban="NL81BUNQ2163127125",
)


def _config(rclone_remote: str | None = "gdrive:vastgoed") -> Config:
    return Config(
        google_service_account_file="fake.json", properties_file="properties.json", bunq_conf_file="fake.conf",
        bunq_environment="PRODUCTION", bunq_api_key=None, users_file="users.json", flask_secret_key="test-secret",
        bedrag_tolerantie=Decimal("0.01"), vooruitbetaling_dagen=14, rclone_remote=rclone_remote,
    )


def test_is_ingesteld():
    assert drive_browse.is_ingesteld(_config("gdrive:vastgoed")) is True
    assert drive_browse.is_ingesteld(_config(None)) is False


def test_list_bestanden_zonder_rclone_remote_geeft_foutmelding():
    with pytest.raises(DriveBrowseError):
        drive_browse.list_bestanden(_config(None), PAND)


def test_list_bestanden_bouwt_juiste_rclone_opdracht(monkeypatch):
    opgevangen = {}

    def _fake_run(cmd, **kwargs):
        opgevangen["cmd"] = cmd
        return MagicMock(returncode=0, stdout=b"[]")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    drive_browse.list_bestanden(_config(), PAND, "Huidige huurders/Jane Doe")
    assert opgevangen["cmd"] == [
        "rclone", "lsjson", "gdrive:vastgoed/Steenhub Mahoniestraat 15/Huidige huurders/Jane Doe",
    ]


def test_list_bestanden_geeft_items_gesorteerd_mappen_eerst(monkeypatch):
    ruw = [
        {"Name": "contract.pdf", "IsDir": False, "Size": 1234, "ModTime": "2026-07-01T10:00:00Z", "MimeType": "application/pdf"},
        {"Name": "Aanvullend", "IsDir": True, "ModTime": "2026-07-02T10:00:00Z"},
    ]
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kwargs: MagicMock(returncode=0, stdout=json.dumps(ruw).encode()))
    items = drive_browse.list_bestanden(_config(), PAND, "")
    assert [i.naam for i in items] == ["Aanvullend", "contract.pdf"]
    assert items[0].is_map is True
    assert items[0].pad == "Aanvullend"
    assert items[1].is_map is False
    assert items[1].pad == "contract.pdf"
    assert items[1].grootte == 1234
    assert items[1].gewijzigd_op == "2026-07-01"


def test_list_bestanden_map_bestaat_nog_niet_geeft_lege_lijst(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kwargs: MagicMock(returncode=1, stdout=b""))
    assert drive_browse.list_bestanden(_config(), PAND, "onbekende-map") == []


def test_list_bestanden_timeout_geeft_foutmelding(monkeypatch):
    def _raise(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="rclone", timeout=60)

    monkeypatch.setattr(subprocess, "run", _raise)
    with pytest.raises(DriveBrowseError):
        drive_browse.list_bestanden(_config(), PAND)


def test_lees_bestand_geeft_inhoud_terug(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kwargs: MagicMock(returncode=0, stdout=b"hallo"))
    assert drive_browse.lees_bestand(_config(), PAND, "contract.pdf") == b"hallo"


def test_lees_bestand_onbekend_bestand_geeft_foutmelding(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kwargs: MagicMock(returncode=1, stdout=b""))
    with pytest.raises(DriveBrowseError):
        drive_browse.lees_bestand(_config(), PAND, "onbekend.pdf")


def test_upload_bestand_roept_rcat_aan_met_juist_pad(monkeypatch):
    opgevangen = {}

    def _fake_run(cmd, input=None, **kwargs):
        opgevangen["cmd"] = cmd
        opgevangen["input"] = input
        return MagicMock(returncode=0)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    drive_browse.upload_bestand(_config(), PAND, "Huidige huurders/Jane Doe", "id.jpg", b"fake-bytes")
    assert opgevangen["cmd"] == [
        "rclone", "rcat", "gdrive:vastgoed/Steenhub Mahoniestraat 15/Huidige huurders/Jane Doe/id.jpg",
    ]
    assert opgevangen["input"] == b"fake-bytes"


def test_upload_bestand_mislukt_geeft_foutmelding(monkeypatch):
    def _raise(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "rclone")

    monkeypatch.setattr(subprocess, "run", _raise)
    with pytest.raises(DriveBrowseError):
        drive_browse.upload_bestand(_config(), PAND, "", "id.jpg", b"fake-bytes")


def test_maak_map_roept_mkdir_aan_met_juist_pad(monkeypatch):
    opgevangen = {}

    def _fake_run(cmd, **kwargs):
        opgevangen["cmd"] = cmd
        return MagicMock(returncode=0)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    drive_browse.maak_map(_config(), PAND, "Huidige huurders", "Nieuwe map")
    assert opgevangen["cmd"] == ["rclone", "mkdir", "gdrive:vastgoed/Steenhub Mahoniestraat 15/Huidige huurders/Nieuwe map"]


def test_maak_map_mislukt_geeft_foutmelding(monkeypatch):
    def _raise(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "rclone")

    monkeypatch.setattr(subprocess, "run", _raise)
    with pytest.raises(DriveBrowseError):
        drive_browse.maak_map(_config(), PAND, "", "Nieuwe map")


# --- drive_sync.hernoem_huurder_map -----------------------------------------

def test_hernoem_huurder_map_verplaatst_en_voegt_samen(monkeypatch):
    from kamerverhuur_scanner import drive_sync
    opgevangen = {}

    def _fake_run(cmd, **kwargs):
        opgevangen["cmd"] = cmd
        return MagicMock(returncode=0)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    assert drive_sync.hernoem_huurder_map(_config(), PAND, "Jane Doe", "Jane Amanda Doe") is True
    assert opgevangen["cmd"] == [
        "rclone", "move",
        "gdrive:vastgoed/Steenhub Mahoniestraat 15/Huidige huurders/Jane Doe",
        "gdrive:vastgoed/Steenhub Mahoniestraat 15/Huidige huurders/Jane Amanda Doe",
        "--delete-empty-src-dirs",
    ]


def test_hernoem_huurder_map_gelijke_naam_doet_niets(monkeypatch):
    from kamerverhuur_scanner import drive_sync
    aangeroepen = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kwargs: aangeroepen.append(cmd) or MagicMock(returncode=0))
    # zelfde naam (ook hoofdletterongevoelig) en lege namen: geen rclone-actie.
    assert drive_sync.hernoem_huurder_map(_config(), PAND, "Jane Doe", "jane doe") is False
    assert drive_sync.hernoem_huurder_map(_config(), PAND, "", "Jane Doe") is False
    assert drive_sync.hernoem_huurder_map(_config(), PAND, "Jane Doe", "") is False
    assert aangeroepen == []


def test_hernoem_huurder_map_zonder_koppeling_doet_niets(monkeypatch):
    from kamerverhuur_scanner import drive_sync
    aangeroepen = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kwargs: aangeroepen.append(cmd) or MagicMock(returncode=0))
    assert drive_sync.hernoem_huurder_map(_config(None), PAND, "Jane Doe", "Jane Amanda Doe") is False
    assert aangeroepen == []

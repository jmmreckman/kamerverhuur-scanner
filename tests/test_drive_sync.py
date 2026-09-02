from decimal import Decimal

from kamerverhuur_scanner import drive_sync
from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.models import Pand

PAND = Pand(
    slug="mahoniestraat", naam="Mahoniestraat 15", google_sheet_id="x", google_sheet_worksheet="Huurders",
    history_worksheet="Historie", bunq_rekening_iban="NL81BUNQ2163127125",
)


def _config(rclone_remote: str | None) -> Config:
    return Config(
        google_service_account_file="fake.json", properties_file="properties.json", bunq_conf_file="fake.conf",
        bunq_environment="PRODUCTION", bunq_api_key=None, users_file="users.json", flask_secret_key="test",
        bedrag_tolerantie=Decimal("0.01"), vooruitbetaling_dagen=14, rclone_remote=rclone_remote,
    )


def test_zonder_rclone_remote_doet_niets(monkeypatch):
    aangeroepen = []
    monkeypatch.setattr(drive_sync.subprocess, "run", lambda *a, **k: aangeroepen.append(a))
    config = _config(None)
    assert drive_sync.upload_bestand(config, PAND, "Luisa", "contract.pdf", b"x") is False
    assert drive_sync.maak_huurder_map(config, PAND, "Luisa") is False
    assert drive_sync.verhuis_naar_oude_huurders(config, PAND, "Luisa") is False
    assert aangeroepen == []


def test_upload_bestand_roept_rclone_rcat_met_juist_pad(monkeypatch):
    aangeroepen = []

    def _fake_run(cmd, **kwargs):
        aangeroepen.append((cmd, kwargs))
        class Resultaat:
            pass
        return Resultaat()

    monkeypatch.setattr(drive_sync.subprocess, "run", _fake_run)
    config = _config("gdrive:vastgoed")
    ok = drive_sync.upload_bestand(config, PAND, "Luisa Fernandez", "contract.pdf", b"inhoud")
    assert ok is True
    (cmd, kwargs), = aangeroepen
    assert cmd == [
        "rclone", "rcat", "gdrive:vastgoed/Steenhub Mahoniestraat 15/Huidige huurders/Luisa Fernandez/contract.pdf",
    ]
    assert kwargs["input"] == b"inhoud"


def test_maak_huurder_map_roept_rclone_mkdir(monkeypatch):
    aangeroepen = []
    monkeypatch.setattr(drive_sync.subprocess, "run", lambda cmd, **k: aangeroepen.append(cmd))
    config = _config("gdrive:vastgoed")
    assert drive_sync.maak_huurder_map(config, PAND, "Luisa") is True
    assert aangeroepen == [
        ["rclone", "mkdir", "gdrive:vastgoed/Steenhub Mahoniestraat 15/Huidige huurders/Luisa"],
    ]


def test_verhuis_naar_oude_huurders_roept_rclone_moveto(monkeypatch):
    aangeroepen = []
    monkeypatch.setattr(drive_sync.subprocess, "run", lambda cmd, **k: aangeroepen.append(cmd))
    config = _config("gdrive:vastgoed")
    assert drive_sync.verhuis_naar_oude_huurders(config, PAND, "Luisa") is True
    assert aangeroepen == [[
        "rclone", "moveto",
        "gdrive:vastgoed/Steenhub Mahoniestraat 15/Huidige huurders/Luisa",
        "gdrive:vastgoed/Steenhub Mahoniestraat 15/Oude huurders/Luisa",
    ]]


def test_mislukte_rclone_opdracht_faalt_stil(monkeypatch):
    import subprocess as sp

    def _fake_run(cmd, **kwargs):
        raise sp.CalledProcessError(1, cmd)

    monkeypatch.setattr(drive_sync.subprocess, "run", _fake_run)
    config = _config("gdrive:vastgoed")
    assert drive_sync.upload_bestand(config, PAND, "Luisa", "contract.pdf", b"x") is False
    assert drive_sync.maak_huurder_map(config, PAND, "Luisa") is False
    assert drive_sync.verhuis_naar_oude_huurders(config, PAND, "Luisa") is False


def test_zonder_huurder_naam_doet_niets(monkeypatch):
    aangeroepen = []
    monkeypatch.setattr(drive_sync.subprocess, "run", lambda *a, **k: aangeroepen.append(a))
    config = _config("gdrive:vastgoed")
    assert drive_sync.upload_bestand(config, PAND, "", "contract.pdf", b"x") is False
    assert aangeroepen == []

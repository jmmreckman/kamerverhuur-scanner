"""Tests voor het ophalen van het per-kamer WWSO-rapport uit de Drive
(webapp/wwso.py) - rclone wordt nooit echt aangeroepen, alleen een
nep-subprocess.run() net als in test_drive_browse.py."""
import json
import subprocess
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.models import Pand
from webapp import wwso
from webapp.wwso import WwsoOntbreekt

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


def _lsjson(namen: list[str]) -> bytes:
    return json.dumps([
        {"Name": n, "IsDir": False, "Size": 10, "ModTime": "2026-07-01T10:00:00Z", "MimeType": "application/pdf"}
        for n in namen
    ]).encode()


# --- wwso_jaar --------------------------------------------------------------

def test_wwso_jaar_uit_ingangsdatum():
    assert wwso.wwso_jaar({"ingangsdatum_iso": "2026-07-01"}) == 2026


def test_wwso_jaar_valt_terug_op_huidig_jaar_bij_ontbrekende_datum():
    from datetime import date
    assert wwso.wwso_jaar({}) == date.today().year
    assert wwso.wwso_jaar({"ingangsdatum_iso": "onzin"}) == date.today().year


# --- haal_wwso_bijlage ------------------------------------------------------

def test_haal_wwso_bijlage_vindt_pdf_op_kamernaam(monkeypatch):
    aanroepen = []

    def _fake_run(cmd, **kwargs):
        aanroepen.append(cmd)
        if cmd[1] == "lsjson":
            return MagicMock(returncode=0, stdout=_lsjson(["bg tuinkant.pdf", "1e etage.pdf"]))
        return MagicMock(returncode=0, stdout=b"%PDF-inhoud")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    naam, mimetype, inhoud = wwso.haal_wwso_bijlage(_config(), PAND, "BG Tuinkant", 2026)
    assert naam == "bg tuinkant.pdf"
    assert mimetype == "application/pdf"
    assert inhoud == b"%PDF-inhoud"
    # er is in de jaar-map van dit pand gezocht.
    assert aanroepen[0] == [
        "rclone", "lsjson", "gdrive:vastgoed/Steenhub Mahoniestraat 15/wwso/2026",
    ]


def test_haal_wwso_bijlage_matcht_hoofdletter_en_spatie_ongevoelig(monkeypatch):
    def _fake_run(cmd, **kwargs):
        if cmd[1] == "lsjson":
            return MagicMock(returncode=0, stdout=_lsjson(["BG  Tuinkant.PDF"]))
        return MagicMock(returncode=0, stdout=b"%PDF")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    naam, _, _ = wwso.haal_wwso_bijlage(_config(), PAND, "bg tuinkant", 2026)
    assert naam == "BG  Tuinkant.PDF"


def test_haal_wwso_bijlage_zonder_drive_koppeling_waarschuwt(monkeypatch):
    with pytest.raises(WwsoOntbreekt):
        wwso.haal_wwso_bijlage(_config(None), PAND, "bg tuinkant", 2026)


def test_haal_wwso_bijlage_lege_map_waarschuwt(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kwargs: MagicMock(returncode=1, stdout=b""))
    with pytest.raises(WwsoOntbreekt) as exc:
        wwso.haal_wwso_bijlage(_config(), PAND, "bg tuinkant", 2026)
    assert "wwso/2026" in str(exc.value)


def test_haal_wwso_bijlage_verkeerde_naam_noemt_beschikbare_bestanden(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, **kwargs: MagicMock(returncode=0, stdout=_lsjson(["1e etage.pdf", "2e etage.pdf"])),
    )
    with pytest.raises(WwsoOntbreekt) as exc:
        wwso.haal_wwso_bijlage(_config(), PAND, "bg tuinkant", 2026)
    bericht = str(exc.value)
    assert "bg tuinkant.pdf" in bericht
    assert "1e etage.pdf" in bericht and "2e etage.pdf" in bericht


def test_haal_wwso_bijlage_zonder_kamernaam_waarschuwt():
    with pytest.raises(WwsoOntbreekt):
        wwso.haal_wwso_bijlage(_config(), PAND, "", 2026)


def test_haal_wwso_bijlage_download_mislukt_waarschuwt(monkeypatch):
    def _fake_run(cmd, **kwargs):
        if cmd[1] == "lsjson":
            return MagicMock(returncode=0, stdout=_lsjson(["bg tuinkant.pdf"]))
        return MagicMock(returncode=1, stdout=b"")  # cat mislukt

    monkeypatch.setattr(subprocess, "run", _fake_run)
    with pytest.raises(WwsoOntbreekt):
        wwso.haal_wwso_bijlage(_config(), PAND, "bg tuinkant", 2026)

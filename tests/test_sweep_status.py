from rotterdam_scanner import sweep_status
from rotterdam_scanner.config import Config


def _config(tmp_path, **overrides):
    defaults = dict(
        gmail_address="scanner@example.com", gmail_app_password="x", report_to=["x@example.com"],
        funda_mail_folder="INBOX", listing_expiry_days=30, opkoopbescherming_woz_grens=470_000,
        state_path=tmp_path / "state.json",
    )
    defaults.update(overrides)
    return Config(**defaults)


def test_laad_zonder_bestand_geeft_idle(tmp_path):
    status = sweep_status.laad(_config(tmp_path))
    assert status.status == "idle"
    assert status.fouten == []


def test_zet_bezig_slaat_status_op(tmp_path):
    config = _config(tmp_path)
    sweep_status.zet_bezig(config)
    status = sweep_status.laad(config)
    assert status.status == "bezig"
    assert status.gestart_op is not None


def test_zet_klaar_behoudt_gestart_op_en_slaat_resultaat_op(tmp_path):
    config = _config(tmp_path)
    sweep_status.zet_bezig(config)
    gestart_op = sweep_status.laad(config).gestart_op

    sweep_status.zet_klaar(config, nieuw_actief=3, nieuw_afgevallen=1, fouten=["een waarschuwing"])
    status = sweep_status.laad(config)
    assert status.status == "klaar"
    assert status.gestart_op == gestart_op
    assert status.klaar_op is not None
    assert status.nieuw_actief == 3
    assert status.nieuw_afgevallen == 1
    assert status.fouten == ["een waarschuwing"]


def test_zet_mislukt_slaat_fout_op(tmp_path):
    config = _config(tmp_path)
    sweep_status.zet_bezig(config)
    sweep_status.zet_mislukt(config, "Apify-run mislukt: boom")
    status = sweep_status.laad(config)
    assert status.status == "mislukt"
    assert status.fouten == ["Apify-run mislukt: boom"]


def test_laad_met_kapot_json_bestand_geeft_idle(tmp_path):
    config = _config(tmp_path)
    sweep_status._pad(config).parent.mkdir(parents=True, exist_ok=True)
    sweep_status._pad(config).write_text("dit is geen json", encoding="utf-8")
    assert sweep_status.laad(config).status == "idle"


def test_zet_bezig_met_url_slaat_url_op(tmp_path):
    config = _config(tmp_path)
    sweep_status.zet_bezig(config, url="https://www.funda.nl/koop/pernis/")
    status = sweep_status.laad(config)
    assert status.url == "https://www.funda.nl/koop/pernis/"


def test_zet_bezig_zonder_url_is_none(tmp_path):
    config = _config(tmp_path)
    sweep_status.zet_bezig(config)
    assert sweep_status.laad(config).url is None


def test_zet_klaar_behoudt_url(tmp_path):
    config = _config(tmp_path)
    sweep_status.zet_bezig(config, url="https://www.funda.nl/koop/pernis/")
    sweep_status.zet_klaar(config, nieuw_actief=1, nieuw_afgevallen=0, fouten=[])
    assert sweep_status.laad(config).url == "https://www.funda.nl/koop/pernis/"


def test_zet_mislukt_behoudt_url(tmp_path):
    config = _config(tmp_path)
    sweep_status.zet_bezig(config, url="https://www.funda.nl/koop/pernis/")
    sweep_status.zet_mislukt(config, "boom")
    assert sweep_status.laad(config).url == "https://www.funda.nl/koop/pernis/"


def test_laad_met_onbekende_status_geeft_idle(tmp_path):
    config = _config(tmp_path)
    sweep_status._pad(config).parent.mkdir(parents=True, exist_ok=True)
    sweep_status._pad(config).write_text('{"status": "onzin"}', encoding="utf-8")
    assert sweep_status.laad(config).status == "idle"

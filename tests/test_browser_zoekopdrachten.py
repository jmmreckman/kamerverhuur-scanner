from rotterdam_scanner import browser_zoekopdrachten
from rotterdam_scanner.config import Config


def _config(tmp_path, **overrides):
    defaults = dict(
        gmail_address="scanner@example.com", gmail_app_password="x", report_to=["x@example.com"],
        funda_mail_folder="INBOX", listing_expiry_days=30, opkoopbescherming_woz_grens=470_000,
        state_path=tmp_path / "state.json",
    )
    defaults.update(overrides)
    return Config(**defaults)


def test_laad_zonder_bestand_geeft_lege_lijst(tmp_path):
    config = _config(tmp_path)
    assert browser_zoekopdrachten.laad(config) == []
    assert browser_zoekopdrachten.laad_met_labels(config) == []


def test_voeg_toe_maakt_bestand_aan_en_slaat_url_op(tmp_path):
    config = _config(tmp_path)
    resultaat = browser_zoekopdrachten.voeg_toe(config, "https://www.funda.nl/zoeken/koop?selected_area=rotterdam")
    assert resultaat == [{"label": "", "url": "https://www.funda.nl/zoeken/koop?selected_area=rotterdam"}]
    assert browser_zoekopdrachten.laad(config) == ["https://www.funda.nl/zoeken/koop?selected_area=rotterdam"]


def test_voeg_toe_slaat_label_op(tmp_path):
    config = _config(tmp_path)
    resultaat = browser_zoekopdrachten.voeg_toe(
        config, "https://www.funda.nl/zoeken/koop?selected_area=rotterdam", "Rotterdam t/m 8 ton"
    )
    assert resultaat == [
        {"label": "Rotterdam t/m 8 ton", "url": "https://www.funda.nl/zoeken/koop?selected_area=rotterdam"}
    ]
    assert browser_zoekopdrachten.laad_met_labels(config) == resultaat


def test_voeg_toe_negeert_duplicaten_op_url(tmp_path):
    config = _config(tmp_path)
    browser_zoekopdrachten.voeg_toe(config, "https://www.funda.nl/zoeken/koop?a=1", "Eerste label")
    resultaat = browser_zoekopdrachten.voeg_toe(config, "https://www.funda.nl/zoeken/koop?a=1", "Ander label")
    assert resultaat == [{"label": "Eerste label", "url": "https://www.funda.nl/zoeken/koop?a=1"}]


def test_voeg_toe_negeert_lege_waarde(tmp_path):
    config = _config(tmp_path)
    resultaat = browser_zoekopdrachten.voeg_toe(config, "   ")
    assert resultaat == []


def test_voeg_toe_meerdere_urls(tmp_path):
    config = _config(tmp_path)
    browser_zoekopdrachten.voeg_toe(config, "https://www.funda.nl/zoeken/koop?a=1", "RDAM")
    resultaat = browser_zoekopdrachten.voeg_toe(config, "https://www.funda.nl/zoeken/koop?a=2", "HvH")
    assert resultaat == [
        {"label": "RDAM", "url": "https://www.funda.nl/zoeken/koop?a=1"},
        {"label": "HvH", "url": "https://www.funda.nl/zoeken/koop?a=2"},
    ]


def test_verwijder_haalt_url_uit_lijst(tmp_path):
    config = _config(tmp_path)
    browser_zoekopdrachten.voeg_toe(config, "https://www.funda.nl/zoeken/koop?a=1")
    browser_zoekopdrachten.voeg_toe(config, "https://www.funda.nl/zoeken/koop?a=2")
    resultaat = browser_zoekopdrachten.verwijder(config, "https://www.funda.nl/zoeken/koop?a=1")
    assert resultaat == [{"label": "", "url": "https://www.funda.nl/zoeken/koop?a=2"}]


def test_verwijder_onbekende_url_verandert_niets(tmp_path):
    config = _config(tmp_path)
    browser_zoekopdrachten.voeg_toe(config, "https://www.funda.nl/zoeken/koop?a=1")
    resultaat = browser_zoekopdrachten.verwijder(config, "https://www.funda.nl/zoeken/koop?onbekend=1")
    assert resultaat == [{"label": "", "url": "https://www.funda.nl/zoeken/koop?a=1"}]


def test_laad_met_kapot_json_bestand_geeft_lege_lijst(tmp_path):
    config = _config(tmp_path)
    browser_zoekopdrachten._pad(config).parent.mkdir(parents=True, exist_ok=True)
    browser_zoekopdrachten._pad(config).write_text("dit is geen json", encoding="utf-8")
    assert browser_zoekopdrachten.laad(config) == []

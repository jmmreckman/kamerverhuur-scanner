from rotterdam_scanner import zoek_urls
from rotterdam_scanner.config import Config


def _config(tmp_path, **overrides):
    defaults = dict(
        gmail_address="scanner@example.com", gmail_app_password="x", report_to=["x@example.com"],
        funda_mail_folder="INBOX", listing_expiry_days=30, opkoopbescherming_woz_grens=470_000,
        state_path=tmp_path / "state.json",
    )
    defaults.update(overrides)
    return Config(**defaults)


def test_laad_zonder_bestand_valt_terug_op_env_instelling(tmp_path):
    config = _config(tmp_path, apify_search_urls=["https://www.funda.nl/koop/rotterdam/"])
    assert zoek_urls.laad(config) == ["https://www.funda.nl/koop/rotterdam/"]


def test_laad_met_labels_zonder_bestand_valt_terug_op_env_instelling(tmp_path):
    config = _config(tmp_path, apify_search_urls=["https://www.funda.nl/koop/rotterdam/"])
    assert zoek_urls.laad_met_labels(config) == [
        {"label": "", "url": "https://www.funda.nl/koop/rotterdam/"}
    ]


def test_voeg_toe_maakt_bestand_aan_en_slaat_url_op(tmp_path):
    config = _config(tmp_path)
    resultaat = zoek_urls.voeg_toe(config, "https://www.funda.nl/koop/rotterdam/")
    assert resultaat == [{"label": "", "url": "https://www.funda.nl/koop/rotterdam/"}]
    assert zoek_urls.laad(config) == ["https://www.funda.nl/koop/rotterdam/"]


def test_voeg_toe_slaat_label_op(tmp_path):
    config = _config(tmp_path)
    resultaat = zoek_urls.voeg_toe(config, "https://www.funda.nl/koop/rotterdam/", "RDAM 100 m2+ <400k")
    assert resultaat == [{"label": "RDAM 100 m2+ <400k", "url": "https://www.funda.nl/koop/rotterdam/"}]
    assert zoek_urls.laad_met_labels(config) == resultaat


def test_voeg_toe_negeert_duplicaten_op_url(tmp_path):
    config = _config(tmp_path)
    zoek_urls.voeg_toe(config, "https://www.funda.nl/koop/rotterdam/", "Eerste label")
    resultaat = zoek_urls.voeg_toe(config, "https://www.funda.nl/koop/rotterdam/", "Ander label")
    assert resultaat == [{"label": "Eerste label", "url": "https://www.funda.nl/koop/rotterdam/"}]


def test_voeg_toe_negeert_lege_waarde(tmp_path):
    config = _config(tmp_path)
    resultaat = zoek_urls.voeg_toe(config, "   ")
    assert resultaat == []


def test_voeg_toe_meerdere_urls(tmp_path):
    config = _config(tmp_path)
    zoek_urls.voeg_toe(config, "https://www.funda.nl/koop/rotterdam/", "RDAM")
    resultaat = zoek_urls.voeg_toe(config, "https://www.funda.nl/koop/hoek-van-holland/", "HvH")
    assert resultaat == [
        {"label": "RDAM", "url": "https://www.funda.nl/koop/rotterdam/"},
        {"label": "HvH", "url": "https://www.funda.nl/koop/hoek-van-holland/"},
    ]


def test_verwijder_haalt_url_uit_lijst(tmp_path):
    config = _config(tmp_path)
    zoek_urls.voeg_toe(config, "https://www.funda.nl/koop/rotterdam/")
    zoek_urls.voeg_toe(config, "https://www.funda.nl/koop/hoek-van-holland/")
    resultaat = zoek_urls.verwijder(config, "https://www.funda.nl/koop/rotterdam/")
    assert resultaat == [{"label": "", "url": "https://www.funda.nl/koop/hoek-van-holland/"}]


def test_verwijder_tot_lege_lijst_valt_niet_meer_terug_op_env(tmp_path):
    # Zodra het bestand bestaat (ook als het leeg is) is het leidend - anders zou een
    # bewuste verwijdering van de laatste URL de env-instelling weer laten "herleven".
    config = _config(tmp_path, apify_search_urls=["https://www.funda.nl/koop/rotterdam/"])
    zoek_urls.voeg_toe(config, "https://www.funda.nl/koop/rotterdam/")
    resultaat = zoek_urls.verwijder(config, "https://www.funda.nl/koop/rotterdam/")
    assert resultaat == []
    assert zoek_urls.laad(config) == []


def test_verwijder_onbekende_url_verandert_niets(tmp_path):
    config = _config(tmp_path)
    zoek_urls.voeg_toe(config, "https://www.funda.nl/koop/rotterdam/")
    resultaat = zoek_urls.verwijder(config, "https://www.funda.nl/koop/onbekend/")
    assert resultaat == [{"label": "", "url": "https://www.funda.nl/koop/rotterdam/"}]


def test_laad_met_kapot_json_bestand_valt_terug_op_env(tmp_path):
    config = _config(tmp_path, apify_search_urls=["https://www.funda.nl/koop/rotterdam/"])
    zoek_urls._pad(config).parent.mkdir(parents=True, exist_ok=True)
    zoek_urls._pad(config).write_text("dit is geen json", encoding="utf-8")
    assert zoek_urls.laad(config) == ["https://www.funda.nl/koop/rotterdam/"]


def test_laad_migreert_oud_formaat_platte_lijst_van_urls(tmp_path):
    # Bestanden van vóór de labels-feature bevatten gewoon een lijst van URL-strings.
    config = _config(tmp_path)
    zoek_urls._pad(config).parent.mkdir(parents=True, exist_ok=True)
    zoek_urls._pad(config).write_text(
        '["https://www.funda.nl/koop/rotterdam/"]', encoding="utf-8"
    )
    assert zoek_urls.laad(config) == ["https://www.funda.nl/koop/rotterdam/"]
    assert zoek_urls.laad_met_labels(config) == [
        {"label": "", "url": "https://www.funda.nl/koop/rotterdam/"}
    ]


def test_voeg_toe_na_oud_formaat_behoudt_bestaande_urls_en_voegt_label_toe(tmp_path):
    config = _config(tmp_path)
    zoek_urls._pad(config).parent.mkdir(parents=True, exist_ok=True)
    zoek_urls._pad(config).write_text(
        '["https://www.funda.nl/koop/rotterdam/"]', encoding="utf-8"
    )
    resultaat = zoek_urls.voeg_toe(config, "https://www.funda.nl/koop/hoek-van-holland/", "HvH")
    assert resultaat == [
        {"label": "", "url": "https://www.funda.nl/koop/rotterdam/"},
        {"label": "HvH", "url": "https://www.funda.nl/koop/hoek-van-holland/"},
    ]

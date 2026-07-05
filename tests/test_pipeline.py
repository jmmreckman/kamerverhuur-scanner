from datetime import date
from unittest.mock import patch

from rotterdam_scanner import pipeline
from rotterdam_scanner.config import Config
from rotterdam_scanner.funda_mail import FundaListing
from rotterdam_scanner.geocode import GeocodeError, GeocodeResult


def _config(tmp_path):
    return Config(
        gmail_address="scanner@example.com",
        gmail_app_password="dummy",
        report_to=["jmmreckman@example.com"],
        funda_mail_folder="INBOX",
        listing_expiry_days=60,
        opkoopbescherming_woz_grens=470_000,
        state_path=tmp_path / "state.json",
    )


def _listing(object_id="1", straat="Teststraat", huisnummer="1"):
    return FundaListing(
        object_id=object_id,
        url=f"https://www.funda.nl/detail/koop/rotterdam/huis-teststraat-{huisnummer}/{object_id}/",
        woonplaats="Rotterdam",
        straatnaam=straat,
        huisnummer=huisnummer,
    )


def _geo(wijk="Rotterdam Centrum"):
    return GeocodeResult(
        weergavenaam="Teststraat 1, 3000AA Rotterdam",
        straatnaam="Teststraat",
        huisnummer="1",
        postcode="3000AA",
        woonplaats="Rotterdam",
        rotterdam_wijk=wijk,
        cbs_wijknaam="Rotterdam Centrum",
        rd_x=90000.0,
        rd_y=435000.0,
    )


def test_listing_zonder_adres_wordt_onbekend(tmp_path):
    listing = FundaListing(object_id="1", url="https://www.funda.nl/detail/x/1/", woonplaats="Rotterdam", straatnaam=None, huisnummer=None)
    result = pipeline._process_new_listing(listing, _config(tmp_path), date(2026, 7, 5))
    assert result.status == "onbekend_adres"


def test_geocode_fout_geeft_onbekend_adres(tmp_path):
    with patch("rotterdam_scanner.pipeline.geocode_address", side_effect=GeocodeError("geen match")):
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "onbekend_adres"
    assert "geen match" in result.afvalreden


def test_nulquotum_laat_huis_afvallen(tmp_path):
    with patch("rotterdam_scanner.pipeline.geocode_address", return_value=_geo()), patch(
        "rotterdam_scanner.pipeline.in_nulquotum_gebied", return_value=True
    ), patch("rotterdam_scanner.pipeline.binnen_50m_van_kamerverhuurvergunning", return_value=False):
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "afgevallen"
    assert "nul-quotumgebied" in result.afvalreden


def test_50m_vergunning_laat_huis_afvallen(tmp_path):
    with patch("rotterdam_scanner.pipeline.geocode_address", return_value=_geo()), patch(
        "rotterdam_scanner.pipeline.in_nulquotum_gebied", return_value=False
    ), patch("rotterdam_scanner.pipeline.binnen_50m_van_kamerverhuurvergunning", return_value=True):
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "afgevallen"
    assert "50 meter" in result.afvalreden


def test_huis_dat_alle_geo_checks_doorstaat_wordt_actief_met_woz_vlag(tmp_path):
    with patch("rotterdam_scanner.pipeline.geocode_address", return_value=_geo(wijk="Middelland")), patch(
        "rotterdam_scanner.pipeline.in_nulquotum_gebied", return_value=False
    ), patch("rotterdam_scanner.pipeline.binnen_50m_van_kamerverhuurvergunning", return_value=False):
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "actief"
    assert result.woz_check_nodig is True
    assert result.woz_check_url == "https://www.wozwaardeloket.nl/"


def test_huis_buiten_beschermde_wijk_heeft_geen_woz_vlag(tmp_path):
    with patch("rotterdam_scanner.pipeline.geocode_address", return_value=_geo(wijk="Rotterdam Centrum")), patch(
        "rotterdam_scanner.pipeline.in_nulquotum_gebied", return_value=False
    ), patch("rotterdam_scanner.pipeline.binnen_50m_van_kamerverhuurvergunning", return_value=False):
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "actief"
    assert result.woz_check_nodig is False


def test_run_verwerkt_alleen_nieuwe_listings_en_update_laatst_gezien(tmp_path):
    config = _config(tmp_path)

    with patch("rotterdam_scanner.pipeline.fetch_recent_funda_listings", return_value=[_listing("1")]), patch(
        "rotterdam_scanner.pipeline.geocode_address", return_value=_geo()
    ), patch("rotterdam_scanner.pipeline.in_nulquotum_gebied", return_value=False), patch(
        "rotterdam_scanner.pipeline.binnen_50m_van_kamerverhuurvergunning", return_value=False
    ):
        result_dag1 = pipeline.run(config, today=date(2026, 7, 1))

    assert len(result_dag1.nieuw_actief) == 1
    assert len(result_dag1.alle_actief) == 1

    with patch("rotterdam_scanner.pipeline.fetch_recent_funda_listings", return_value=[_listing("1")]), patch(
        "rotterdam_scanner.pipeline.geocode_address"
    ) as geocode_mock:
        result_dag2 = pipeline.run(config, today=date(2026, 7, 5))

    geocode_mock.assert_not_called()
    assert len(result_dag2.nieuw_actief) == 0
    assert len(result_dag2.alle_actief) == 1
    assert result_dag2.alle_actief[0].eerst_gezien == "2026-07-01"
    assert result_dag2.alle_actief[0].laatst_gezien == "2026-07-05"


def test_run_meldt_fout_bij_kapotte_mailbox_zonder_te_crashen(tmp_path):
    config = _config(tmp_path)
    with patch("rotterdam_scanner.pipeline.fetch_recent_funda_listings", side_effect=RuntimeError("IMAP kapot")):
        result = pipeline.run(config, today=date(2026, 7, 5))
    assert result.fouten
    assert "IMAP kapot" in result.fouten[0]

from datetime import date
from unittest.mock import patch

import pytest

from rotterdam_scanner import pipeline
from rotterdam_scanner.config import Config
from rotterdam_scanner.funda_mail import FundaListing, FundaMailScan
from rotterdam_scanner.geocode import GeocodeError, GeocodeResult


@pytest.fixture(autouse=True)
def _geen_verwijder_commandos_tenzij_expliciet_gemockt():
    with patch("rotterdam_scanner.pipeline.fetch_verwijder_commandos", return_value=set()):
        yield


def _config(tmp_path, **overrides):
    defaults = dict(
        gmail_address="scanner@example.com",
        gmail_app_password="dummy",
        report_to=["jmmreckman@example.com"],
        funda_mail_folder="INBOX",
        listing_expiry_days=60,
        opkoopbescherming_woz_grens=470_000,
        state_path=tmp_path / "state.json",
    )
    defaults.update(overrides)
    return Config(**defaults)


def _listing(object_id="1", straat="Teststraat", huisnummer="1", prijs=None):
    return FundaListing(
        object_id=object_id,
        url=f"https://www.funda.nl/detail/koop/rotterdam/huis-teststraat-{huisnummer}/{object_id}/",
        woonplaats="Rotterdam",
        straatnaam=straat,
        huisnummer=huisnummer,
        prijs=prijs,
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
        nummeraanduiding_id="0599200000239721",
        adresseerbaarobject_id="0599010000156729",
    )


def _patch_geo_checks(wijk="Rotterdam Centrum", nulquotum=False, binnen_50m=False, oppervlakte=100):
    return (
        patch("rotterdam_scanner.pipeline.geocode_address", return_value=_geo(wijk=wijk)),
        patch("rotterdam_scanner.pipeline.in_nulquotum_gebied", return_value=nulquotum),
        patch("rotterdam_scanner.pipeline.binnen_50m_van_kamerverhuurvergunning", return_value=binnen_50m),
        patch("rotterdam_scanner.pipeline.fetch_bag_oppervlakte", return_value=oppervlakte),
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
    p1, p2, p3, p4 = _patch_geo_checks(nulquotum=True)
    with p1, p2, p3, p4:
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "afgevallen"
    assert "nul-quotumgebied" in result.afvalreden


def test_50m_vergunning_laat_huis_afvallen(tmp_path):
    p1, p2, p3, p4 = _patch_geo_checks(binnen_50m=True)
    with p1, p2, p3, p4:
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "afgevallen"
    assert "50 meter" in result.afvalreden


def test_huis_dat_alle_geo_checks_doorstaat_wordt_actief_met_woz_vlag(tmp_path):
    p1, p2, p3, p4 = _patch_geo_checks(wijk="Middelland")
    with p1, p2, p3, p4:
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "actief"
    assert result.woz_check_nodig is True
    assert result.woz_check_url == "https://www.wozwaardeloket.nl/"


def test_huis_buiten_beschermde_wijk_heeft_geen_woz_vlag(tmp_path):
    p1, p2, p3, p4 = _patch_geo_checks(wijk="Rotterdam Centrum")
    with p1, p2, p3, p4:
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "actief"
    assert result.woz_check_nodig is False


def test_bag_oppervlakte_en_prijs_worden_meegenomen_op_actieve_woning(tmp_path):
    p1, p2, p3, p4 = _patch_geo_checks(wijk="Rotterdam Centrum", oppervlakte=80)
    with p1, p2, p3, p4:
        result = pipeline._process_new_listing(_listing(prijs=320_000), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "actief"
    assert result.bag_oppervlakte == 80
    assert result.prijs == 320_000
    assert result.prijs_per_m2 == 4000.0


def test_bag_fout_geeft_opmerking_maar_geen_crash(tmp_path):
    with patch("rotterdam_scanner.pipeline.geocode_address", return_value=_geo()), patch(
        "rotterdam_scanner.pipeline.in_nulquotum_gebied", return_value=False
    ), patch("rotterdam_scanner.pipeline.binnen_50m_van_kamerverhuurvergunning", return_value=False), patch(
        "rotterdam_scanner.pipeline.fetch_bag_oppervlakte", side_effect=RuntimeError("BAG plat")
    ):
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "actief"
    assert result.bag_oppervlakte is None
    assert "BAG plat" in result.opmerking


def test_woz_api_onder_grens_laat_huis_automatisch_afvallen(tmp_path):
    from rotterdam_scanner.woz import WozWaarde

    with patch("rotterdam_scanner.pipeline.geocode_address", return_value=_geo(wijk="Middelland")), patch(
        "rotterdam_scanner.pipeline.in_nulquotum_gebied", return_value=False
    ), patch("rotterdam_scanner.pipeline.binnen_50m_van_kamerverhuurvergunning", return_value=False), patch(
        "rotterdam_scanner.pipeline.meest_recente_woz_waarde",
        return_value=WozWaarde(peildatum="2025-01-01", bedrag=300_000),
    ):
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))

    assert result.status == "afgevallen"
    assert "WOZ-waarde" in result.afvalreden


def test_woz_api_boven_grens_laat_huis_actief_zonder_handmatige_vlag(tmp_path):
    from rotterdam_scanner.woz import WozWaarde

    p1, p2, p3, p4 = _patch_geo_checks(wijk="Middelland")
    with p1, p2, p3, p4, patch(
        "rotterdam_scanner.pipeline.meest_recente_woz_waarde",
        return_value=WozWaarde(peildatum="2025-01-01", bedrag=600_000),
    ):
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))

    assert result.status == "actief"
    assert result.woz_check_nodig is False
    assert result.opmerking is None


def test_woz_api_fout_valt_terug_op_handmatige_vlag_met_opmerking(tmp_path):
    with patch("rotterdam_scanner.pipeline.geocode_address", return_value=_geo(wijk="Middelland")), patch(
        "rotterdam_scanner.pipeline.in_nulquotum_gebied", return_value=False
    ), patch("rotterdam_scanner.pipeline.binnen_50m_van_kamerverhuurvergunning", return_value=False), patch(
        "rotterdam_scanner.pipeline.meest_recente_woz_waarde", side_effect=RuntimeError("API plat")
    ):
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))

    assert result.status == "actief"
    assert result.woz_check_nodig is True
    assert "API plat" in result.opmerking


def test_run_verwerkt_alleen_nieuwe_listings_en_update_laatst_gezien(tmp_path):
    config = _config(tmp_path)

    p1, p2, p3, p4 = _patch_geo_checks()
    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan",
        return_value=FundaMailScan(listings=[_listing("1")]),
    ), p1, p2, p3, p4:
        result_dag1 = pipeline.run(config, today=date(2026, 7, 1))

    assert len(result_dag1.nieuw_actief) == 1
    assert len(result_dag1.alle_actief) == 1

    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan",
        return_value=FundaMailScan(listings=[_listing("1")]),
    ), patch("rotterdam_scanner.pipeline.geocode_address") as geocode_mock:
        result_dag2 = pipeline.run(config, today=date(2026, 7, 5))

    geocode_mock.assert_not_called()
    assert len(result_dag2.nieuw_actief) == 0
    assert len(result_dag2.alle_actief) == 1
    assert result_dag2.alle_actief[0].eerst_gezien == "2026-07-01"
    assert result_dag2.alle_actief[0].laatst_gezien == "2026-07-05"


def test_run_meldt_fout_bij_kapotte_mailbox_zonder_te_crashen(tmp_path):
    config = _config(tmp_path)
    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan", side_effect=RuntimeError("IMAP kapot")
    ):
        result = pipeline.run(config, today=date(2026, 7, 5))
    assert result.fouten
    assert "IMAP kapot" in result.fouten[0]


def test_run_haalt_bestaande_actieve_woning_weg_bij_verwijder_commando(tmp_path):
    config = _config(tmp_path)
    p1, p2, p3, p4 = _patch_geo_checks()

    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan",
        return_value=FundaMailScan(listings=[_listing("1")]),
    ), p1, p2, p3, p4:
        result_dag1 = pipeline.run(config, today=date(2026, 7, 1))
    assert len(result_dag1.alle_actief) == 1

    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan",
        return_value=FundaMailScan(listings=[]),
    ), patch("rotterdam_scanner.pipeline.fetch_verwijder_commandos", return_value={"1"}):
        result_dag2 = pipeline.run(config, today=date(2026, 7, 2))

    assert len(result_dag2.alle_actief) == 0
    assert len(result_dag2.handmatig_verwijderd) == 1
    assert "Handmatig verwijderd" in result_dag2.handmatig_verwijderd[0].afvalreden


def test_run_nieuwe_listing_met_meteen_verwijder_commando_wordt_niet_actief(tmp_path):
    config = _config(tmp_path)
    p1, p2, p3, p4 = _patch_geo_checks()

    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan",
        return_value=FundaMailScan(listings=[_listing("1")]),
    ), patch("rotterdam_scanner.pipeline.fetch_verwijder_commandos", return_value={"1"}), p1, p2, p3, p4:
        result = pipeline.run(config, today=date(2026, 7, 1))

    assert len(result.alle_actief) == 0
    assert len(result.nieuw_actief) == 0
    assert any("Handmatig verwijderd" in item.afvalreden for item in result.nieuw_afgevallen)


def test_run_meldt_fout_bij_kapotte_verwijder_commando_scan_zonder_te_crashen(tmp_path):
    config = _config(tmp_path)
    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan", return_value=FundaMailScan(listings=[])
    ), patch("rotterdam_scanner.pipeline.fetch_verwijder_commandos", side_effect=RuntimeError("IMAP kapot")):
        result = pipeline.run(config, today=date(2026, 7, 5))
    assert result.fouten
    assert "IMAP kapot" in result.fouten[0]


def test_run_sorteert_openstaande_kansen_op_prijs_per_m2(tmp_path):
    config = _config(tmp_path)

    def geocode_side_effect(straat, huisnummer, woonplaats):
        return _geo(wijk="Rotterdam Centrum")

    def oppervlakte_side_effect(_id):
        return 100

    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan",
        return_value=FundaMailScan(
            listings=[
                _listing("duur", straat="Duurstraat", prijs=500_000),
                _listing("goedkoop", straat="Goedkoopstraat", prijs=200_000),
                _listing("midden", straat="Middenstraat", prijs=300_000),
            ]
        ),
    ), patch("rotterdam_scanner.pipeline.geocode_address", side_effect=geocode_side_effect), patch(
        "rotterdam_scanner.pipeline.in_nulquotum_gebied", return_value=False
    ), patch("rotterdam_scanner.pipeline.binnen_50m_van_kamerverhuurvergunning", return_value=False), patch(
        "rotterdam_scanner.pipeline.fetch_bag_oppervlakte", side_effect=oppervlakte_side_effect
    ):
        result = pipeline.run(config, today=date(2026, 7, 1))

    volgorde = [item.object_id for item in result.alle_actief]
    assert volgorde == ["goedkoop", "midden", "duur"]


def test_run_zet_woningen_zonder_prijs_achteraan_de_sortering(tmp_path):
    config = _config(tmp_path)

    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan",
        return_value=FundaMailScan(
            listings=[
                _listing("zonder_prijs", straat="Onbekendstraat", prijs=None),
                _listing("met_prijs", straat="Bekendstraat", prijs=100_000),
            ]
        ),
    ), patch("rotterdam_scanner.pipeline.geocode_address", return_value=_geo()), patch(
        "rotterdam_scanner.pipeline.in_nulquotum_gebied", return_value=False
    ), patch("rotterdam_scanner.pipeline.binnen_50m_van_kamerverhuurvergunning", return_value=False), patch(
        "rotterdam_scanner.pipeline.fetch_bag_oppervlakte", return_value=100
    ):
        result = pipeline.run(config, today=date(2026, 7, 1))

    volgorde = [item.object_id for item in result.alle_actief]
    assert volgorde == ["met_prijs", "zonder_prijs"]

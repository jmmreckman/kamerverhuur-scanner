from datetime import date
from unittest.mock import patch

import pytest

from rotterdam_scanner import pipeline
from rotterdam_scanner.bag import BagGegevens
from rotterdam_scanner.config import Config
from rotterdam_scanner.funda_mail import FundaListing, FundaMailScan
from rotterdam_scanner.geocode import GeocodeError, GeocodeResult
from rotterdam_scanner.monumenten import HuurprijsopslagSignaal


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
        listing_expiry_days=30,
        opkoopbescherming_woz_grens=470_000,
        state_path=tmp_path / "state.json",
    )
    defaults.update(overrides)
    return Config(**defaults)


def _listing(
    object_id="3000AA-1",
    straat="Teststraat",
    huisnummer="1",
    postcode="3000AA",
    toevoeging="",
    prijs=None,
    oppervlakte_advertentie=None,
):
    return FundaListing(
        object_id=object_id,
        url=f"https://links.funda.nl/s/c/token-{object_id}/hash/22",
        straatnaam=straat,
        huisnummer=huisnummer,
        toevoeging=toevoeging,
        postcode=postcode,
        woonplaats="Rotterdam",
        prijs=prijs,
        oppervlakte_advertentie=oppervlakte_advertentie,
    )


def _onbekende_listing(object_id="onbekend"):
    return FundaListing(
        object_id=object_id,
        url=f"https://links.funda.nl/s/c/token-{object_id}/hash/22",
        straatnaam=None,
        huisnummer=None,
        toevoeging="",
        postcode=None,
        woonplaats=None,
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


def _patch_geo_checks(wijk="Rotterdam Centrum", nulquotum=False, binnen_50m=False, oppervlakte=100, bouwjaar=None):
    return (
        patch("rotterdam_scanner.pipeline.geocode_by_postcode", return_value=_geo(wijk=wijk)),
        patch("rotterdam_scanner.pipeline.in_nulquotum_gebied", return_value=nulquotum),
        patch("rotterdam_scanner.pipeline.binnen_50m_van_kamerverhuurvergunning", return_value=binnen_50m),
        patch(
            "rotterdam_scanner.pipeline.fetch_bag_gegevens",
            return_value=BagGegevens(oppervlakte=oppervlakte, bouwjaar=bouwjaar),
        ),
        patch("rotterdam_scanner.pipeline.bepaal_huurprijsopslag", return_value=[]),
    )


def test_listing_zonder_adres_wordt_onbekend(tmp_path):
    result = pipeline._process_new_listing(_onbekende_listing(), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "onbekend_adres"


def test_geocode_fout_geeft_onbekend_adres(tmp_path):
    with patch("rotterdam_scanner.pipeline.geocode_by_postcode", side_effect=GeocodeError("geen match")):
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "onbekend_adres"
    assert "geen match" in result.afvalreden


def test_nulquotum_laat_huis_afvallen(tmp_path):
    p1, p2, p3, p4, p5 = _patch_geo_checks(nulquotum=True)
    with p1, p2, p3, p4, p5:
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "afgevallen"
    assert "nul-quotumgebied" in result.afvalreden


def test_50m_vergunning_laat_huis_afvallen(tmp_path):
    p1, p2, p3, p4, p5 = _patch_geo_checks(binnen_50m=True)
    with p1, p2, p3, p4, p5:
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "afgevallen"
    assert "50 meter" in result.afvalreden


def test_50m_regel_geldt_niet_meer_bij_3_kamers_of_minder(tmp_path):
    # 54 m2 BAG-oppervlakte -> floor(54/18) = 3 kamers, precies op de grens.
    p1, p2, p3, p4, p5 = _patch_geo_checks(binnen_50m=True, oppervlakte=54)
    with p1, p2, p3, p4, p5:
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "actief"
    assert result.aantal_kamers_mogelijk == 3
    assert "50-meter-regel niet van toepassing" in result.opmerking


def test_50m_regel_geldt_nog_gewoon_bij_4_kamers(tmp_path):
    # 72 m2 BAG-oppervlakte -> floor(72/18) = 4 kamers, net boven de grens.
    p1, p2, p3, p4, p5 = _patch_geo_checks(binnen_50m=True, oppervlakte=72)
    with p1, p2, p3, p4, p5:
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "afgevallen"
    assert "50 meter" in result.afvalreden


def test_50m_regel_blijft_gelden_als_aantal_kamers_onbekend_is(tmp_path):
    # BAG-storing -> aantal kamers onbekend -> voor de zekerheid blijft de regel gelden.
    with patch("rotterdam_scanner.pipeline.geocode_by_postcode", return_value=_geo()), patch(
        "rotterdam_scanner.pipeline.in_nulquotum_gebied", return_value=False
    ), patch("rotterdam_scanner.pipeline.binnen_50m_van_kamerverhuurvergunning", return_value=True), patch(
        "rotterdam_scanner.pipeline.fetch_bag_gegevens", side_effect=RuntimeError("BAG plat")
    ):
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "afgevallen"
    assert "50 meter" in result.afvalreden


def test_huis_dat_alle_geo_checks_doorstaat_wordt_actief_met_woz_vlag(tmp_path):
    p1, p2, p3, p4, p5 = _patch_geo_checks(wijk="Middelland")
    with p1, p2, p3, p4, p5:
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "actief"
    assert result.woz_check_nodig is True
    assert result.woz_check_url == "https://www.wozwaardeloket.nl/"


def test_huis_buiten_beschermde_wijk_heeft_geen_woz_vlag(tmp_path):
    p1, p2, p3, p4, p5 = _patch_geo_checks(wijk="Rotterdam Centrum")
    with p1, p2, p3, p4, p5:
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "actief"
    assert result.woz_check_nodig is False


def test_bag_oppervlakte_en_prijs_worden_meegenomen_op_actieve_woning(tmp_path):
    p1, p2, p3, p4, p5 = _patch_geo_checks(wijk="Rotterdam Centrum", oppervlakte=80)
    with p1, p2, p3, p4, p5:
        result = pipeline._process_new_listing(_listing(prijs=320_000), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "actief"
    assert result.bag_oppervlakte == 80
    assert result.prijs == 320_000
    assert result.prijs_per_m2 == 4000.0


def test_oppervlakte_advertentie_en_aantal_kamers_worden_meegenomen(tmp_path):
    p1, p2, p3, p4, p5 = _patch_geo_checks(wijk="Rotterdam Centrum", oppervlakte=115)
    with p1, p2, p3, p4, p5:
        result = pipeline._process_new_listing(
            _listing(prijs=403_000, oppervlakte_advertentie=120), _config(tmp_path), date(2026, 7, 5)
        )
    assert result.status == "actief"
    assert result.oppervlakte_advertentie == 120
    # aantal_kamers_mogelijk gaat uit van de officiële BAG-oppervlakte (115), niet de
    # advertentietekst (120) - zelfde 6 kamers als het geverifieerde referentievoorbeeld.
    assert result.aantal_kamers_mogelijk == 6


def test_aantal_kamers_mogelijk_ook_bekend_zonder_vraagprijs(tmp_path):
    # Kamers volgen alleen uit de BAG-oppervlakte, dus dat kan al getoond worden ook
    # als de vraagprijs (nog) niet uit de mail te herleiden was.
    p1, p2, p3, p4, p5 = _patch_geo_checks(wijk="Rotterdam Centrum", oppervlakte=115)
    with p1, p2, p3, p4, p5:
        result = pipeline._process_new_listing(_listing(prijs=None), _config(tmp_path), date(2026, 7, 5))
    assert result.aantal_kamers_mogelijk == 6
    assert result.winst_pm_pp is None
    assert result.eigen_inleg_pp is None


def test_huurprijsopslag_signalen_worden_meegenomen_op_actieve_woning(tmp_path):
    p1, p2, p3, p4, _ = _patch_geo_checks(wijk="Rotterdam Centrum", bouwjaar=1918)
    signaal = HuurprijsopslagSignaal(percentage=0.35, tekst="Mogelijk rijksmonument (35%)")
    with p1, p2, p3, p4, patch(
        "rotterdam_scanner.pipeline.bepaal_huurprijsopslag", return_value=[signaal]
    ) as signalen_mock:
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "actief"
    assert result.huurprijsopslag_signalen == ["Mogelijk rijksmonument (35%)"]
    signalen_mock.assert_called_once_with(90000.0, 435000.0, 1918)


def test_monumentencheck_fout_geeft_opmerking_maar_geen_crash(tmp_path):
    p1, p2, p3, p4, _ = _patch_geo_checks(wijk="Rotterdam Centrum")
    with p1, p2, p3, p4, patch(
        "rotterdam_scanner.pipeline.bepaal_huurprijsopslag", side_effect=RuntimeError("RCE plat")
    ):
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "actief"
    assert result.huurprijsopslag_signalen == []
    assert "RCE plat" in result.opmerking


def test_bag_fout_geeft_opmerking_maar_geen_crash(tmp_path):
    with patch("rotterdam_scanner.pipeline.geocode_by_postcode", return_value=_geo()), patch(
        "rotterdam_scanner.pipeline.in_nulquotum_gebied", return_value=False
    ), patch("rotterdam_scanner.pipeline.binnen_50m_van_kamerverhuurvergunning", return_value=False), patch(
        "rotterdam_scanner.pipeline.fetch_bag_gegevens", side_effect=RuntimeError("BAG plat")
    ), patch("rotterdam_scanner.pipeline.bepaal_huurprijsopslag", return_value=[]):
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "actief"
    assert result.bag_oppervlakte is None
    assert "BAG plat" in result.opmerking


def test_woz_api_onder_grens_laat_huis_automatisch_afvallen(tmp_path):
    from rotterdam_scanner.woz import WozWaarde

    with patch("rotterdam_scanner.pipeline.geocode_by_postcode", return_value=_geo(wijk="Middelland")), patch(
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

    p1, p2, p3, p4, p5 = _patch_geo_checks(wijk="Middelland")
    with p1, p2, p3, p4, p5, patch(
        "rotterdam_scanner.pipeline.meest_recente_woz_waarde",
        return_value=WozWaarde(peildatum="2025-01-01", bedrag=600_000),
    ):
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))

    assert result.status == "actief"
    assert result.woz_check_nodig is False
    assert result.opmerking is None


def test_woz_api_fout_valt_terug_op_handmatige_vlag_met_opmerking(tmp_path):
    with patch("rotterdam_scanner.pipeline.geocode_by_postcode", return_value=_geo(wijk="Middelland")), patch(
        "rotterdam_scanner.pipeline.in_nulquotum_gebied", return_value=False
    ), patch("rotterdam_scanner.pipeline.binnen_50m_van_kamerverhuurvergunning", return_value=False), patch(
        "rotterdam_scanner.pipeline.meest_recente_woz_waarde", side_effect=RuntimeError("API plat")
    ), patch("rotterdam_scanner.pipeline.fetch_bag_gegevens", return_value=None), patch(
        "rotterdam_scanner.pipeline.bepaal_huurprijsopslag", return_value=[]
    ):
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))

    assert result.status == "actief"
    assert result.woz_check_nodig is True
    assert "API plat" in result.opmerking


def test_run_verwerkt_alleen_nieuwe_listings_en_update_laatst_gezien(tmp_path):
    config = _config(tmp_path)

    p1, p2, p3, p4, p5 = _patch_geo_checks()
    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan",
        return_value=FundaMailScan(listings=[_listing()]),
    ), p1, p2, p3, p4, p5:
        result_dag1 = pipeline.run(config, today=date(2026, 7, 1))

    assert len(result_dag1.nieuw_actief) == 1
    assert len(result_dag1.alle_actief) == 1

    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan",
        return_value=FundaMailScan(listings=[_listing()]),
    ), patch("rotterdam_scanner.pipeline.geocode_by_postcode") as geocode_mock:
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


def test_run_geeft_scan_waarschuwingen_door(tmp_path):
    config = _config(tmp_path)
    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan",
        return_value=FundaMailScan(listings=[], waarschuwingen=["let op: niet alles herkend"]),
    ):
        result = pipeline.run(config, today=date(2026, 7, 5))
    assert "let op: niet alles herkend" in result.fouten


def test_run_haalt_bestaande_actieve_woning_weg_bij_verwijder_commando(tmp_path):
    config = _config(tmp_path)
    p1, p2, p3, p4, p5 = _patch_geo_checks()

    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan",
        return_value=FundaMailScan(listings=[_listing()]),
    ), p1, p2, p3, p4, p5:
        result_dag1 = pipeline.run(config, today=date(2026, 7, 1))
    assert len(result_dag1.alle_actief) == 1
    object_id = result_dag1.alle_actief[0].object_id

    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan",
        return_value=FundaMailScan(listings=[]),
    ), patch("rotterdam_scanner.pipeline.fetch_verwijder_commandos", return_value={object_id}):
        result_dag2 = pipeline.run(config, today=date(2026, 7, 2))

    assert len(result_dag2.alle_actief) == 0
    assert len(result_dag2.handmatig_verwijderd) == 1
    assert "Handmatig verwijderd" in result_dag2.handmatig_verwijderd[0].afvalreden


def test_run_nieuwe_listing_met_meteen_verwijder_commando_wordt_niet_actief(tmp_path):
    config = _config(tmp_path)
    p1, p2, p3, p4, p5 = _patch_geo_checks()
    listing = _listing()

    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan",
        return_value=FundaMailScan(listings=[listing]),
    ), patch(
        "rotterdam_scanner.pipeline.fetch_verwijder_commandos", return_value={listing.object_id}
    ), p1, p2, p3, p4, p5:
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


def test_run_sorteert_openstaande_kansen_op_eigen_inleg_pp(tmp_path):
    # Zelfde BAG-oppervlakte (dus zelfde aantal kamers/kale huur/taxatie na
    # vergunning) voor alle drie - alleen de vraagprijs verschilt, dus een lagere
    # vraagprijs geeft hier ook een lagere eigen inleg p.p. (zelfde volgorde als de
    # oude prijs-per-m2-sortering, maar nu getest tegen de echte sorteersleutel).
    config = _config(tmp_path)

    def geocode_side_effect(postcode, huisnummer, toevoeging=""):
        return _geo(wijk="Rotterdam Centrum")

    def bag_side_effect(_id):
        return BagGegevens(oppervlakte=100, bouwjaar=None)

    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan",
        return_value=FundaMailScan(
            listings=[
                _listing("duur", straat="Duurstraat", postcode="3001AA", prijs=500_000),
                _listing("goedkoop", straat="Goedkoopstraat", postcode="3002AA", prijs=200_000),
                _listing("midden", straat="Middenstraat", postcode="3003AA", prijs=300_000),
            ]
        ),
    ), patch("rotterdam_scanner.pipeline.geocode_by_postcode", side_effect=geocode_side_effect), patch(
        "rotterdam_scanner.pipeline.in_nulquotum_gebied", return_value=False
    ), patch("rotterdam_scanner.pipeline.binnen_50m_van_kamerverhuurvergunning", return_value=False), patch(
        "rotterdam_scanner.pipeline.fetch_bag_gegevens", side_effect=bag_side_effect
    ), patch("rotterdam_scanner.pipeline.bepaal_huurprijsopslag", return_value=[]):
        result = pipeline.run(config, today=date(2026, 7, 1))

    volgorde = [item.object_id for item in result.alle_actief]
    assert volgorde == ["goedkoop", "midden", "duur"]


def test_run_zet_woningen_zonder_prijs_achteraan_de_sortering(tmp_path):
    config = _config(tmp_path)

    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan",
        return_value=FundaMailScan(
            listings=[
                _listing("zonder_prijs", straat="Onbekendstraat", postcode="3004AA", prijs=None),
                _listing("met_prijs", straat="Bekendstraat", postcode="3005AA", prijs=100_000),
            ]
        ),
    ), patch("rotterdam_scanner.pipeline.geocode_by_postcode", return_value=_geo()), patch(
        "rotterdam_scanner.pipeline.in_nulquotum_gebied", return_value=False
    ), patch("rotterdam_scanner.pipeline.binnen_50m_van_kamerverhuurvergunning", return_value=False), patch(
        "rotterdam_scanner.pipeline.fetch_bag_gegevens", return_value=BagGegevens(oppervlakte=100, bouwjaar=None)
    ), patch("rotterdam_scanner.pipeline.bepaal_huurprijsopslag", return_value=[]):
        result = pipeline.run(config, today=date(2026, 7, 1))

    volgorde = [item.object_id for item in result.alle_actief]
    assert volgorde == ["met_prijs", "zonder_prijs"]


def test_run_backvult_investeringscijfers_voor_bestaande_woningen_zonder_ze_opnieuw_te_verwerken(tmp_path):
    # Simuleert een woning die al in state.json stond vóórdat de investeringsberekening
    # bestond: winst_pm_pp/eigen_inleg_pp zijn nog None, terwijl bag_oppervlakte en
    # prijs (nodig om ze alsnog te berekenen) al wel bekend waren. Verschijnt vandaag
    # niet eens in de Funda-mail - moet toch bijgewerkt worden, zonder opnieuw te
    # geocoderen/BAG/monumenten te bevragen (dat zou hier meteen falen/gemockt moeten
    # zijn als het geprobeerd werd).
    from rotterdam_scanner.state import ListingState, StateStore

    config = _config(tmp_path)
    state = StateStore(config.state_path)
    state.upsert(
        ListingState(
            object_id="oude-woning",
            url="https://example.com/oude-woning",
            weergavenaam="Oudstraat 1, Rotterdam",
            eerst_gezien="2026-06-25",
            laatst_gezien="2026-06-30",
            status="actief",
            bag_oppervlakte=115,
            prijs=403_000,
            opslag_percentage=0.0,
        )
    )
    state.save()

    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan", return_value=FundaMailScan(listings=[])
    ):
        result = pipeline.run(config, today=date(2026, 7, 1))

    bijgewerkt = next(item for item in result.alle_actief if item.object_id == "oude-woning")
    assert round(bijgewerkt.winst_pm_pp, 2) == 972.63
    assert round(bijgewerkt.eigen_inleg_pp, 2) == 27_721.05
    assert bijgewerkt.aantal_kamers_mogelijk == 6


def test_run_backvult_aantal_kamers_ook_zonder_bekende_prijs(tmp_path):
    # aantal_kamers_mogelijk heeft geen prijs nodig (alleen bag_oppervlakte), dus moet
    # ook bijgevuld worden voor oude woningen waarvan de vraagprijs nooit bekend werd.
    from rotterdam_scanner.state import ListingState, StateStore

    config = _config(tmp_path)
    state = StateStore(config.state_path)
    state.upsert(
        ListingState(
            object_id="oude-woning-zonder-prijs",
            url="https://example.com/oude-woning-zonder-prijs",
            weergavenaam="Oudstraat 2, Rotterdam",
            eerst_gezien="2026-06-25",
            laatst_gezien="2026-06-30",
            status="actief",
            bag_oppervlakte=115,
            prijs=None,
        )
    )
    state.save()

    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan", return_value=FundaMailScan(listings=[])
    ):
        result = pipeline.run(config, today=date(2026, 7, 1))

    bijgewerkt = next(item for item in result.alle_actief if item.object_id == "oude-woning-zonder-prijs")
    assert bijgewerkt.aantal_kamers_mogelijk == 6
    assert bijgewerkt.winst_pm_pp is None
    assert bijgewerkt.eigen_inleg_pp is None


def test_run_handmatig_verwerkt_lijst_zonder_funda_mail_of_verwijder_check(tmp_path):
    config = _config(tmp_path)
    p1, p2, p3, p4, p5 = _patch_geo_checks()

    with patch("rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan") as mail_mock, p1, p2, p3, p4, p5:
        result = pipeline.run_handmatig(config, [_listing()], today=date(2026, 7, 1))

    mail_mock.assert_not_called()
    assert len(result.nieuw_actief) == 1
    assert len(result.alle_actief) == 1


def test_run_handmatig_woningen_blijven_staan_voor_volgende_dagelijkse_run(tmp_path):
    config = _config(tmp_path)
    p1, p2, p3, p4, p5 = _patch_geo_checks()

    with p1, p2, p3, p4, p5:
        result_handmatig = pipeline.run_handmatig(config, [_listing()], today=date(2026, 7, 1))
    assert len(result_handmatig.alle_actief) == 1

    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan",
        return_value=FundaMailScan(listings=[]),
    ), patch("rotterdam_scanner.pipeline.geocode_by_postcode") as geocode_mock:
        result_dag = pipeline.run(config, today=date(2026, 7, 2))

    geocode_mock.assert_not_called()
    assert len(result_dag.alle_actief) == 1
    assert result_dag.alle_actief[0].eerst_gezien == "2026-07-01"


def test_run_handmatig_slaat_bekend_adres_standaard_over_ook_na_gewijzigde_check(tmp_path):
    config = _config(tmp_path)
    p1, p2, p3, p4, p5 = _patch_geo_checks()
    with p1, p2, p3, p4, p5:
        pipeline.run_handmatig(config, [_listing()], today=date(2026, 7, 1))

    # Zonder forceer_herprocessen telt een gewijzigde check-uitkomst niet mee voor een
    # adres dat al bekend is -- alleen url/prijs worden ververst.
    p1, p2, p3, p4, p5 = _patch_geo_checks(nulquotum=True)
    with p1, p2, p3, p4, p5:
        result = pipeline.run_handmatig(config, [_listing()], today=date(2026, 7, 2))
    assert len(result.alle_actief) == 1


def test_run_handmatig_forceer_herprocessen_corrigeert_bestaand_adres(tmp_path):
    config = _config(tmp_path)
    p1, p2, p3, p4, p5 = _patch_geo_checks()
    with p1, p2, p3, p4, p5:
        pipeline.run_handmatig(config, [_listing()], today=date(2026, 7, 1))

    p1, p2, p3, p4, p5 = _patch_geo_checks(nulquotum=True)
    with p1, p2, p3, p4, p5:
        result = pipeline.run_handmatig(
            config, [_listing()], today=date(2026, 7, 2), forceer_herprocessen=True
        )
    assert len(result.alle_actief) == 0
    assert len(result.nieuw_afgevallen) == 1


def test_run_handmatig_forceer_herprocessen_laat_handmatig_verwijderde_woning_met_rust(tmp_path):
    config = _config(tmp_path)
    p1, p2, p3, p4, p5 = _patch_geo_checks()
    with p1, p2, p3, p4, p5:
        pipeline.run_handmatig(config, [_listing()], today=date(2026, 7, 1))

    with patch("rotterdam_scanner.pipeline.fetch_verwijder_commandos", return_value={"3000AA-1"}), patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan", return_value=FundaMailScan(listings=[])
    ):
        result_dag = pipeline.run(config, today=date(2026, 7, 2))
    assert len(result_dag.handmatig_verwijderd) == 1
    assert result_dag.alle_actief == []

    p1, p2, p3, p4, p5 = _patch_geo_checks()
    with p1, p2, p3, p4, p5:
        result = pipeline.run_handmatig(
            config, [_listing()], today=date(2026, 7, 3), forceer_herprocessen=True
        )
    assert result.alle_actief == []

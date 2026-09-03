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
    # Standaard geen verwijder-commando's en geen NVM-mails (anders zou run() een
    # echte IMAP-verbinding proberen); tests die dat willen, mocken het expliciet.
    with patch("rotterdam_scanner.pipeline.fetch_verwijder_commandos", return_value=set()), \
         patch("rotterdam_scanner.pipeline.haal_nvm_woningen", return_value=([], [])):
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
        lon=4.4800,
        lat=51.9200,
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


def test_actieve_woning_krijgt_coordinaten_voor_de_kaart(tmp_path):
    p1, p2, p3, p4, p5 = _patch_geo_checks(wijk="Rotterdam Centrum")
    with p1, p2, p3, p4, p5:
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))
    assert result.lat == 51.9200
    assert result.lon == 4.4800


def test_afgevallen_woning_krijgt_ook_coordinaten(tmp_path):
    p1, p2, p3, p4, p5 = _patch_geo_checks(wijk="Rotterdam Centrum", nulquotum=True)
    with p1, p2, p3, p4, p5:
        result = pipeline._process_new_listing(_listing(), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "afgevallen"
    assert result.lat == 51.9200
    assert result.lon == 4.4800


def test_bag_oppervlakte_en_prijs_worden_meegenomen_op_actieve_woning(tmp_path):
    p1, p2, p3, p4, p5 = _patch_geo_checks(wijk="Rotterdam Centrum", oppervlakte=80)
    with p1, p2, p3, p4, p5:
        result = pipeline._process_new_listing(_listing(prijs=320_000), _config(tmp_path), date(2026, 7, 5))
    assert result.status == "actief"
    assert result.bag_oppervlakte == 80
    assert result.prijs == 320_000
    assert result.prijs_per_m2 == 4000.0


def test_oppervlakte_advertentie_en_aantal_kamers_worden_meegenomen(tmp_path):
    # BAG (115) en advertentie (140) geven bewust een ander aantal kamers (6 vs. 7)
    # om te bevestigen dat de advertentie-m2 leidend is (die is betrouwbaarder -
    # BAG geeft soms een te hoge waarde, zie ListingState.primaire_oppervlakte).
    p1, p2, p3, p4, p5 = _patch_geo_checks(wijk="Rotterdam Centrum", oppervlakte=115)
    with p1, p2, p3, p4, p5:
        result = pipeline._process_new_listing(
            _listing(prijs=403_000, oppervlakte_advertentie=140), _config(tmp_path), date(2026, 7, 5)
        )
    assert result.status == "actief"
    assert result.oppervlakte_advertentie == 140
    assert result.bag_oppervlakte == 115
    assert result.primaire_oppervlakte == 140
    assert result.aantal_kamers_mogelijk == 7


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


def test_run_negeert_woning_met_handmatig_verwijderd_vlag_ongeacht_afvalreden_tekst(tmp_path):
    # De bescherming tegen automatisch heractiveren werkt op de handmatig_verwijderd-
    # vlag, niet op de exacte afvalreden-tekst - zo beschermt hetzelfde mechanisme ook
    # een verwijdering via het kruisje op kansen.steenhub.nl (met een eigen, door de
    # gebruiker getypte reden) net zo goed als via de mail-link.
    from rotterdam_scanner.state import ListingState, StateStore

    config = _config(tmp_path)
    state = StateStore(config.state_path)
    state.upsert(ListingState(
        object_id="3000AA-1", url="https://example.com/3000AA-1", weergavenaam="Teststraat 1",
        eerst_gezien="2026-06-01", laatst_gezien="2026-06-30", status="afgevallen",
        afvalreden="Zelfbewoningsplicht", handmatig_verwijderd=True,
    ))
    state.save()

    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan",
        return_value=FundaMailScan(listings=[_listing()]),
    ):
        result = pipeline.run(config, today=date(2026, 7, 1))

    assert result.alle_actief == []
    bijgewerkt = StateStore(config.state_path).get("3000AA-1")
    assert bijgewerkt.status == "afgevallen"
    assert bijgewerkt.afvalreden == "Zelfbewoningsplicht"


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


def test_run_herberekent_kamers_en_investering_op_basis_van_advertentie_m2(tmp_path):
    # Woning die eerder (vóór deze aanpassing) verwerkt is op basis van BAG-m2 (115 ->
    # 6 kamers), terwijl de advertentie-m2 (140 -> 7 kamers) al wel bekend was maar toen
    # nog niet leidend was. Moet bij de eerstvolgende run automatisch gecorrigeerd
    # worden naar de advertentie-m2, zonder dat de woning opnieuw in de mail hoeft te
    # verschijnen.
    from rotterdam_scanner.state import ListingState, StateStore

    config = _config(tmp_path)
    state = StateStore(config.state_path)
    state.upsert(
        ListingState(
            object_id="oude-woning-verkeerde-kamers",
            url="https://example.com/oude-woning-verkeerde-kamers",
            weergavenaam="Oudstraat 3, Rotterdam",
            eerst_gezien="2026-06-25",
            laatst_gezien="2026-06-30",
            status="actief",
            bag_oppervlakte=115,
            oppervlakte_advertentie=140,
            prijs=403_000,
            opslag_percentage=0.0,
            aantal_kamers_mogelijk=6,
        )
    )
    state.save()

    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan", return_value=FundaMailScan(listings=[])
    ):
        result = pipeline.run(config, today=date(2026, 7, 1))

    bijgewerkt = next(item for item in result.alle_actief if item.object_id == "oude-woning-verkeerde-kamers")
    assert bijgewerkt.aantal_kamers_mogelijk == 7


def test_run_backvult_opkoopbescherming_zet_woning_af_bij_lage_woz(tmp_path):
    # Woning in een beschermde wijk die "actief" bleef staan met woz_check_nodig=True
    # (de automatische WOZ-opvraging is de eerste keer mislukt of gaf nog geen resultaat).
    # Als de WOZ-waarde nu wel op te halen is én onder de grens ligt, moet de woning
    # alsnog afvallen - precies zoals hij op dag 1 al had moeten doen.
    from rotterdam_scanner.state import ListingState, StateStore
    from rotterdam_scanner.woz import WozWaarde

    config = _config(tmp_path)
    state = StateStore(config.state_path)
    state.upsert(
        ListingState(
            object_id="3082DD-19B",
            url="https://example.com/grondherendijk-19b",
            weergavenaam="Grondherendijk 19-B, Rotterdam",
            eerst_gezien="2026-06-25",
            laatst_gezien="2026-06-30",
            status="actief",
            straatnaam="Grondherendijk",
            huisnummer="19B",
            wijknaam="Oud Charlois",
            lat=51.894,
            lon=4.4655,
            woz_check_nodig=True,
            woz_check_url="https://www.wozwaardeloket.nl/",
        )
    )
    state.save()

    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan", return_value=FundaMailScan(listings=[])
    ), patch("rotterdam_scanner.pipeline.geocode_by_postcode", return_value=_geo(wijk="Oud Charlois")), patch(
        "rotterdam_scanner.pipeline.meest_recente_woz_waarde",
        return_value=WozWaarde(peildatum="2025-01-01", bedrag=348_000),
    ):
        result = pipeline.run(config, today=date(2026, 7, 1))

    herladen = StateStore(config.state_path)
    bijgewerkt = herladen.get("3082DD-19B")
    assert bijgewerkt.status == "afgevallen"
    assert bijgewerkt.woz_check_nodig is False
    assert "opkoopbescherming" in bijgewerkt.afvalreden
    assert any(item.object_id == "3082DD-19B" for item in result.nieuw_afgevallen)
    assert not any(item.object_id == "3082DD-19B" for item in result.alle_actief)


def test_run_backvult_opkoopbescherming_blijft_actief_bij_hoge_woz(tmp_path):
    from rotterdam_scanner.state import ListingState, StateStore
    from rotterdam_scanner.woz import WozWaarde

    config = _config(tmp_path)
    state = StateStore(config.state_path)
    state.upsert(
        ListingState(
            object_id="3082DD-19B",
            url="https://example.com/grondherendijk-19b",
            weergavenaam="Grondherendijk 19-B, Rotterdam",
            eerst_gezien="2026-06-25",
            laatst_gezien="2026-06-30",
            status="actief",
            straatnaam="Grondherendijk",
            huisnummer="19B",
            wijknaam="Oud Charlois",
            lat=51.894,
            lon=4.4655,
            woz_check_nodig=True,
            woz_check_url="https://www.wozwaardeloket.nl/",
            opmerking="Geen publieke WOZ-waarde gevonden voor dit adres; handmatig checken.",
        )
    )
    state.save()

    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan", return_value=FundaMailScan(listings=[])
    ), patch("rotterdam_scanner.pipeline.geocode_by_postcode", return_value=_geo(wijk="Oud Charlois")), patch(
        "rotterdam_scanner.pipeline.meest_recente_woz_waarde",
        return_value=WozWaarde(peildatum="2025-01-01", bedrag=600_000),
    ):
        pipeline.run(config, today=date(2026, 7, 1))

    herladen = StateStore(config.state_path)
    bijgewerkt = herladen.get("3082DD-19B")
    assert bijgewerkt.status == "actief"
    assert bijgewerkt.woz_check_nodig is False
    # De inmiddels achterhaalde "kon niet gevonden worden"-opmerking van dag 1 moet
    # weg zijn nu de WOZ-waarde alsnog is opgehaald - anders blijft de kaart-popup een
    # verouderde, verwarrende melding tonen.
    assert bijgewerkt.opmerking is None


def test_run_backvult_coordinaten_voor_bestaande_woningen_zonder_lat_lon(tmp_path):
    # Simuleert een woning die al in state.json stond vóórdat coördinaten werden
    # opgeslagen (lat/lon nog None) - moet alsnog gegeocodeerd worden, ook al
    # verschijnt hij vandaag niet opnieuw in de Funda-mail, anders zou hij nooit
    # op de kaart (kansen.steenhub.nl) verschijnen.
    from rotterdam_scanner.state import ListingState, StateStore

    config = _config(tmp_path)
    state = StateStore(config.state_path)
    state.upsert(
        ListingState(
            object_id="3000AA-1", url="https://example.com/oude-woning", weergavenaam="Teststraat 1, Rotterdam",
            eerst_gezien="2026-06-25", laatst_gezien="2026-06-30", status="actief", huisnummer="1",
        )
    )
    state.save()

    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan", return_value=FundaMailScan(listings=[])
    ), patch("rotterdam_scanner.pipeline.geocode_by_postcode", return_value=_geo()) as geocode_mock:
        result = pipeline.run(config, today=date(2026, 7, 1))

    bijgewerkt = next(item for item in result.alle_actief if item.object_id == "3000AA-1")
    assert bijgewerkt.lat == 51.9200
    assert bijgewerkt.lon == 4.4800
    geocode_mock.assert_called_once_with("3000AA", "1", "")


def test_run_backvult_coordinaten_laat_woning_met_lat_met_rust(tmp_path):
    from rotterdam_scanner.state import ListingState, StateStore

    config = _config(tmp_path)
    state = StateStore(config.state_path)
    state.upsert(
        ListingState(
            object_id="3000AA-1", url="https://example.com/al-gegeocodeerd", weergavenaam="Teststraat 1, Rotterdam",
            eerst_gezien="2026-06-25", laatst_gezien="2026-06-30", status="actief", huisnummer="1",
            lat=52.0, lon=4.5,
        )
    )
    state.save()

    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan", return_value=FundaMailScan(listings=[])
    ), patch("rotterdam_scanner.pipeline.geocode_by_postcode") as geocode_mock:
        pipeline.run(config, today=date(2026, 7, 1))

    geocode_mock.assert_not_called()


def test_run_backvult_coordinaten_negeert_afgevallen_woningen(tmp_path):
    from rotterdam_scanner.state import ListingState, StateStore

    config = _config(tmp_path)
    state = StateStore(config.state_path)
    state.upsert(
        ListingState(
            object_id="3000AA-1", url="https://example.com/afgevallen", weergavenaam="Teststraat 1, Rotterdam",
            eerst_gezien="2026-06-25", laatst_gezien="2026-06-30", status="afgevallen", huisnummer="1",
        )
    )
    state.save()

    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan", return_value=FundaMailScan(listings=[])
    ), patch("rotterdam_scanner.pipeline.geocode_by_postcode") as geocode_mock:
        pipeline.run(config, today=date(2026, 7, 1))

    geocode_mock.assert_not_called()


def test_run_backvult_coordinaten_geocode_fout_geeft_geen_crash(tmp_path):
    from rotterdam_scanner.state import ListingState, StateStore

    config = _config(tmp_path)
    state = StateStore(config.state_path)
    state.upsert(
        ListingState(
            object_id="3000AA-1", url="https://example.com/mislukt-geocoderen", weergavenaam="Teststraat 1, Rotterdam",
            eerst_gezien="2026-06-25", laatst_gezien="2026-06-30", status="actief", huisnummer="1",
        )
    )
    state.save()

    with patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan", return_value=FundaMailScan(listings=[])
    ), patch("rotterdam_scanner.pipeline.geocode_by_postcode", side_effect=GeocodeError("geen match")):
        result = pipeline.run(config, today=date(2026, 7, 1))

    bijgewerkt = next(item for item in result.alle_actief if item.object_id == "3000AA-1")
    assert bijgewerkt.lat is None
    assert bijgewerkt.lon is None


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
    # Regressietest: een al bekend adres komt niet in nieuw_actief/afgevallen/
    # onbekend_adres terecht (het wordt alleen bijgewerkt) - zonder al_bekend
    # klopte de som van die drie categorieën niet meer met het aangeleverde
    # aantal, wat op de "Handmatig toevoegen"-pagina verwarrend was.
    assert len(result.al_bekend) == 1
    assert len(result.nieuw_actief) == 0
    assert len(result.nieuw_afgevallen) == 0
    assert len(result.nieuw_onbekend_adres) == 0


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



# --- run_beschikbaarheidscheck ---


def test_run_beschikbaarheidscheck_verwijdert_niet_meer_beschikbare_woning(tmp_path):
    from rotterdam_scanner.state import ListingState, StateStore

    config = _config(tmp_path)
    state = StateStore(config.state_path)
    state.upsert(ListingState(
        object_id="3000AA-1", url="https://www.funda.nl/detail/koop/rotterdam/huis-1/",
        weergavenaam="Teststraat 1", eerst_gezien="2026-06-01", laatst_gezien="2026-06-30",
        status="actief",
    ))
    state.save()

    with patch("rotterdam_scanner.pipeline.controleer_beschikbaar", return_value=False):
        result = pipeline.run_beschikbaarheidscheck(config, today=date(2026, 7, 1))

    bijgewerkt = StateStore(config.state_path).get("3000AA-1")
    assert bijgewerkt.status == "afgevallen"
    assert "verkocht" in bijgewerkt.afvalreden.lower()
    assert bijgewerkt.laatst_gezien == "2026-07-01"
    assert len(result.nieuw_afgevallen) == 1
    assert result.alle_actief == []


def test_run_beschikbaarheidscheck_laat_beschikbare_woning_actief(tmp_path):
    from rotterdam_scanner.state import ListingState, StateStore

    config = _config(tmp_path)
    state = StateStore(config.state_path)
    state.upsert(ListingState(
        object_id="3000AA-1", url="https://www.funda.nl/detail/koop/rotterdam/huis-1/",
        weergavenaam="Teststraat 1", eerst_gezien="2026-06-01", laatst_gezien="2026-06-30",
        status="actief",
    ))
    state.save()

    with patch("rotterdam_scanner.pipeline.controleer_beschikbaar", return_value=True):
        result = pipeline.run_beschikbaarheidscheck(config, today=date(2026, 7, 1))

    bijgewerkt = StateStore(config.state_path).get("3000AA-1")
    assert bijgewerkt.status == "actief"
    assert bijgewerkt.laatst_gezien == "2026-07-01"
    assert result.nieuw_afgevallen == []
    assert len(result.alle_actief) == 1


def test_run_beschikbaarheidscheck_laat_onduidelijk_resultaat_met_rust(tmp_path):
    from rotterdam_scanner.state import ListingState, StateStore

    config = _config(tmp_path)
    state = StateStore(config.state_path)
    state.upsert(ListingState(
        object_id="3000AA-1", url="https://www.funda.nl/detail/koop/rotterdam/huis-1/",
        weergavenaam="Teststraat 1", eerst_gezien="2026-06-01", laatst_gezien="2026-06-30",
        status="actief",
    ))
    state.save()

    with patch("rotterdam_scanner.pipeline.controleer_beschikbaar", return_value=None):
        result = pipeline.run_beschikbaarheidscheck(config, today=date(2026, 7, 1))

    bijgewerkt = StateStore(config.state_path).get("3000AA-1")
    assert bijgewerkt.status == "actief"
    # niet aangeraakt - een onduidelijk resultaat (bv. blokkade) mag laatst_gezien
    # niet ophogen, anders zou een woning die écht van Funda af is nooit via de
    # normale 30-dagen-expiry verlopen.
    assert bijgewerkt.laatst_gezien == "2026-06-30"
    assert result.nieuw_afgevallen == []
    assert len(result.alle_actief) == 1


def test_run_beschikbaarheidscheck_negeert_al_afgevallen_woningen(tmp_path):
    from rotterdam_scanner.state import ListingState, StateStore

    config = _config(tmp_path)
    state = StateStore(config.state_path)
    state.upsert(ListingState(
        object_id="3000AA-1", url="https://www.funda.nl/detail/koop/rotterdam/huis-1/",
        weergavenaam="Teststraat 1", eerst_gezien="2026-06-01", laatst_gezien="2026-06-30",
        status="afgevallen", afvalreden="Ligt in een nul-quotumgebied voor kamerverhuur.",
    ))
    state.save()

    with patch("rotterdam_scanner.pipeline.controleer_beschikbaar") as mock_check:
        pipeline.run_beschikbaarheidscheck(config, today=date(2026, 7, 1))
    mock_check.assert_not_called()


def test_run_beschikbaarheidscheck_roept_check_aan_met_de_opgeslagen_url(tmp_path):
    from rotterdam_scanner.state import ListingState, StateStore

    config = _config(tmp_path)
    state = StateStore(config.state_path)
    state.upsert(ListingState(
        object_id="3000AA-1", url="https://www.funda.nl/detail/koop/rotterdam/huis-1/",
        weergavenaam="Teststraat 1", eerst_gezien="2026-06-01", laatst_gezien="2026-06-30",
        status="actief",
    ))
    state.save()

    with patch("rotterdam_scanner.pipeline.controleer_beschikbaar", return_value=True) as mock_check:
        pipeline.run_beschikbaarheidscheck(config, today=date(2026, 7, 1))
    mock_check.assert_called_once_with("https://www.funda.nl/detail/koop/rotterdam/huis-1/")


# --- Den Haag-routing (andere checkset dan Rotterdam) ---


def _geo_den_haag(wijk="Benoordenhout"):
    return GeocodeResult(
        weergavenaam="Wassenaarseweg 257, 2596 Cas-Gravenhage",
        straatnaam="Wassenaarseweg",
        huisnummer="257",
        postcode="2596CA",
        woonplaats="'s-Gravenhage",
        rotterdam_wijk="een buurt",  # PDOK-buurtnaam (niet relevant voor DH-match)
        cbs_wijknaam=wijk,  # PDOK-wijknaam = Den Haag-wijk
        rd_x=81000.0,
        rd_y=455000.0,
        lon=4.30,
        lat=52.10,
        nummeraanduiding_id="0518200000000001",
        adresseerbaarobject_id="0518010000000001",
    )


def test_den_haag_geschikte_woning_wordt_actief_met_signalen(tmp_path):
    listing = _listing(object_id="2596CA-257", postcode="2596CA", prijs=595000, oppervlakte_advertentie=218)
    with patch("rotterdam_scanner.pipeline.geocode_by_postcode", return_value=_geo_den_haag()), patch(
        "rotterdam_scanner.pipeline.fetch_bag_gegevens", return_value=BagGegevens(oppervlakte=218, bouwjaar=None)
    ):
        result = pipeline._process_new_listing(listing, _config(tmp_path), date(2026, 7, 30))
    assert result.status == "actief"
    assert result.stad == "den_haag"
    assert result.wijknaam == "Benoordenhout"
    assert result.aantal_kamers_mogelijk == 8  # 218 // 18 -> gecapt op 8
    assert result.winst_pm_pp is not None  # investeringscijfers ook voor Den Haag
    assert result.eigen_inleg_pp is not None
    assert any("geluidsisolatie" in s for s in result.check_signalen)


def test_den_haag_niet_toegestane_wijk_valt_af(tmp_path):
    listing = _listing(object_id="x", oppervlakte_advertentie=218)
    with patch("rotterdam_scanner.pipeline.geocode_by_postcode", return_value=_geo_den_haag(wijk="Moerwijk")), patch(
        "rotterdam_scanner.pipeline.fetch_bag_gegevens", return_value=BagGegevens(oppervlakte=218, bouwjaar=None)
    ):
        result = pipeline._process_new_listing(listing, _config(tmp_path), date(2026, 7, 30))
    assert result.status == "afgevallen"
    assert result.stad == "den_haag"
    assert "Leefbaarometer" in result.afvalreden


def test_den_haag_te_kleine_woning_valt_af(tmp_path):
    listing = _listing(object_id="x", oppervlakte_advertentie=90)  # 90 // 18 = 5 < 6
    with patch("rotterdam_scanner.pipeline.geocode_by_postcode", return_value=_geo_den_haag()), patch(
        "rotterdam_scanner.pipeline.fetch_bag_gegevens", return_value=BagGegevens(oppervlakte=90, bouwjaar=None)
    ):
        result = pipeline._process_new_listing(listing, _config(tmp_path), date(2026, 7, 30))
    assert result.status == "afgevallen"
    assert "capaciteit" in result.afvalreden.lower()


def test_straat_adres_zonder_postcode_geocodeert_op_adres_en_krijgt_postcode_id(tmp_path):
    # Een handmatig aangeleverd adres zonder postcode (bv. de lijst van Wout) wordt op
    # straat+plaats gegeocodeerd; de object_id wordt daarna de canonieke POSTCODE-vorm.
    from rotterdam_scanner.funda_mail import FundaListing

    listing = FundaListing(
        object_id="adres:wassenaarseweg 257, den haag",
        url="https://example.com/x",
        straatnaam="Wassenaarseweg", huisnummer="257", toevoeging="",
        postcode=None, woonplaats="Den Haag", oppervlakte_advertentie=218,
    )
    with patch("rotterdam_scanner.pipeline.geocode_address", return_value=_geo_den_haag()) as geo_mock, patch(
        "rotterdam_scanner.pipeline.fetch_bag_gegevens", return_value=BagGegevens(oppervlakte=218, bouwjaar=None)
    ):
        result = pipeline._process_new_listing(listing, _config(tmp_path), date(2026, 7, 30))

    # Op adres (niet op postcode) gegeocodeerd, met Den Haag -> 's-Gravenhage.
    assert geo_mock.call_args[0][0] == "Wassenaarseweg"
    assert geo_mock.call_args[0][2] == "'s-Gravenhage"
    assert result.stad == "den_haag"
    assert result.status == "actief"
    # _geo_den_haag geeft postcode "2596CA" -> canonieke id.
    assert result.object_id == "2596CA-257"


# --- Bron-tracking (Funda + NVM) ---

def _nvm_listing(object_id="3000AA-1", postcode="3000AA", huisnummer="1", prijs=350_000):
    return FundaListing(
        object_id=object_id, url="", straatnaam="Teststraat", huisnummer=huisnummer,
        toevoeging="", postcode=postcode, woonplaats="Rotterdam", prijs=prijs,
        oppervlakte_advertentie=80, bron="nvm",
    )


def test_bron_tracking_nvm_en_funda_ontdubbelen_op_object_id(tmp_path):
    from rotterdam_scanner.state import StateStore
    config = _config(tmp_path)
    state = StateStore(config.state_path)
    result = pipeline.RunResult()
    p1, p2, p3, p4, p5 = _patch_geo_checks()
    with p1, p2, p3, p4, p5:
        # NVM eerst (url=""), Funda daarna (echte link) - zelfde object_id.
        pipeline._verwerk_listings(
            [_nvm_listing(), _listing()], set(), config, date(2026, 7, 5), state, result,
        )
    item = state.get("3000AA-1")
    assert item is not None
    assert item.bronnen == ["nvm", "funda"]  # beide geregistreerd, in volgorde
    assert item.url.startswith("https://links.funda.nl")  # lege NVM-url wist de Funda-link niet


def test_alleen_nvm_woning_houdt_bron_nvm(tmp_path):
    from rotterdam_scanner.state import StateStore
    config = _config(tmp_path)
    state = StateStore(config.state_path)
    result = pipeline.RunResult()
    p1, p2, p3, p4, p5 = _patch_geo_checks()
    with p1, p2, p3, p4, p5:
        pipeline._verwerk_listings(
            [_nvm_listing(object_id="3000BB-2", postcode="3000BB", huisnummer="2")],
            set(), config, date(2026, 7, 5), state, result,
        )
    assert state.get("3000BB-2").bronnen == ["nvm"]


def test_run_combineert_funda_en_nvm(tmp_path):
    from rotterdam_scanner.state import StateStore
    config = _config(tmp_path)
    p1, p2, p3, p4, p5 = _patch_geo_checks()
    with p1, p2, p3, p4, p5, patch(
        "rotterdam_scanner.pipeline.fetch_recent_funda_mail_scan",
        return_value=FundaMailScan(listings=[_listing(object_id="3000AA-1")]),
    ), patch(
        "rotterdam_scanner.pipeline.haal_nvm_woningen",
        return_value=([_nvm_listing(object_id="3000AA-1"),
                       _nvm_listing(object_id="3000BB-2", postcode="3000BB", huisnummer="2")], []),
    ), patch("rotterdam_scanner.pipeline._controleer_favoriet_bekendmakingen"):
        pipeline.run(config, today=date(2026, 7, 5))

    state = StateStore(config.state_path)
    gedeeld = state.get("3000AA-1")
    assert set(gedeeld.bronnen) == {"funda", "nvm"}
    assert gedeeld.url.startswith("https://links.funda.nl")
    assert state.get("3000BB-2").bronnen == ["nvm"]

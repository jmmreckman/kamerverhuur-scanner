from datetime import date

from rotterdam_scanner.pipeline import RunResult
from rotterdam_scanner.report import build_html_report, build_text_report
from rotterdam_scanner.state import ListingState


def _listing(
    object_id,
    weergavenaam,
    eerst_gezien,
    wijknaam="Centrum",
    prijs=250_000,
    bag_oppervlakte=60,
    oppervlakte_advertentie=None,
    aantal_kamers_mogelijk=None,
    winst_pm_pp=None,
    eigen_inleg_pp=None,
):
    return ListingState(
        object_id=object_id,
        url=f"https://example.com/{object_id}",
        weergavenaam=weergavenaam,
        eerst_gezien=eerst_gezien,
        laatst_gezien="2026-07-09",
        status="actief",
        wijknaam=wijknaam,
        prijs=prijs,
        bag_oppervlakte=bag_oppervlakte,
        oppervlakte_advertentie=oppervlakte_advertentie,
        aantal_kamers_mogelijk=aantal_kamers_mogelijk,
        winst_pm_pp=winst_pm_pp,
        eigen_inleg_pp=eigen_inleg_pp,
    )


def test_html_report_toont_bron_telling():
    # Ook bij "0 nieuw" moet zichtbaar zijn dat de bronnen wél woningen leverden
    # (die dan al bekend waren), zodat "0 nieuwe kandidaten" niet als storing oogt.
    item = _listing("OUD-1", "Oudstraat 1, Rotterdam", "2026-06-01")
    result = RunResult(alle_actief=[item], nieuw_actief=[], al_bekend=[item],
                       nvm_gelezen=52, funda_gelezen=2)
    html = build_html_report(result, date(2026, 7, 9), "scanner@example.com")
    assert "52 via NVM-mails" in html
    assert "Funda-alerts" in html
    tekst = build_text_report(result, date(2026, 7, 9), "scanner@example.com")
    assert "52 via NVM" in tekst
    assert "2 via Funda" in tekst


def test_html_report_adres_staat_in_eigen_link():
    # Gmail linkt platte adrestekst automatisch door naar Google Maps, en doet dat over
    # celgrenzen heen (adres + wijknaam samen), wat de tabelstructuur kapotmaakt (extra
    # <td> ertussen). Door het adres zelf al in onze eigen <a> te wrappen, herkent Gmail
    # het niet als "nog te linken" platte tekst en blijft de tabel intact.
    item = _listing("NEW-1", "Nieuwstraat 1, Rotterdam", "2026-07-09")
    result = RunResult(alle_actief=[item], nieuw_actief=[item])

    html = build_html_report(result, date(2026, 7, 9), "scanner@example.com")

    assert f'<a href="{item.url}">Nieuwstraat 1, Rotterdam</a>' in html


def test_html_report_wijknaam_staat_ook_in_eigen_link():
    # Zelfde reden als hierboven: bleek in de praktijk nodig, want Gmail sprong na het
    # linken van het adres gewoon door naar de eerstvolgende ongelinkte tekst (de
    # wijknaam-cel) en injecteerde daar alsnog een kapotte extra <td>.
    item = _listing("NEW-1", "Nieuwstraat 1, Rotterdam", "2026-07-09", wijknaam="Heijplaat")
    result = RunResult(alle_actief=[item], nieuw_actief=[item])

    html = build_html_report(result, date(2026, 7, 9), "scanner@example.com")

    assert '<a href="https://www.google.com/maps/search/Heijplaat%2C%20Rotterdam">Heijplaat</a>' in html


def test_html_report_wijk_heeft_label_zodat_gmail_geen_adres_meer_herkent():
    # Zelfs met beide teksten al in een eigen link injecteerde Gmail in de praktijk nog
    # steeds een lege spookcel tussen adres en wijknaam (gebaseerd op tekstdetectie die
    # kennelijk voor het linken al draait). Een klein label breekt het "regel 2 van een
    # adres"-patroon zodat de detectie er niet meer op aanslaat.
    item = _listing("NEW-1", "Nieuwstraat 1, Rotterdam", "2026-07-09", wijknaam="Heijplaat")
    result = RunResult(alle_actief=[item], nieuw_actief=[item])

    html = build_html_report(result, date(2026, 7, 9), "scanner@example.com")

    assert "wijk: " in html


def test_html_report_zonder_wijknaam_geeft_streepje_zonder_link():
    item = _listing("NEW-1", "Nieuwstraat 1, Rotterdam", "2026-07-09", wijknaam=None)
    result = RunResult(alle_actief=[item], nieuw_actief=[item])

    html = build_html_report(result, date(2026, 7, 9), "scanner@example.com")

    assert "google.com/maps/search" not in html
    assert ">-</td>" in html


def test_html_report_toont_alleen_nieuwe_woningen_in_nieuwe_kansen_blok():
    nieuw = _listing("NEW-1", "Nieuwstraat 1, Rotterdam", "2026-07-09")
    oud = _listing("OLD-1", "Oudstraat 2, Rotterdam", "2026-06-20")
    result = RunResult(alle_actief=[nieuw, oud], nieuw_actief=[nieuw])

    html = build_html_report(result, date(2026, 7, 9), "scanner@example.com")

    nieuwe_sectie = html.split("Rotterdam — nieuwe kansen vandaag")[1].split("Rotterdam — openstaande kansen")[0]
    assert "Nieuwstraat 1" in nieuwe_sectie
    assert "Oudstraat 2" not in nieuwe_sectie

    openstaande_sectie = html.split("Rotterdam — openstaande kansen")[1]
    assert "Nieuwstraat 1" in openstaande_sectie
    assert "Oudstraat 2" in openstaande_sectie


def test_html_report_nieuwe_kansen_blok_toont_geen_woningen_bij_leeg():
    oud = _listing("OLD-1", "Oudstraat 2, Rotterdam", "2026-06-20")
    result = RunResult(alle_actief=[oud], nieuw_actief=[])

    html = build_html_report(result, date(2026, 7, 9), "scanner@example.com")

    assert "nieuwe kansen vandaag (0)" in html
    nieuwe_sectie = html.split("Rotterdam — nieuwe kansen vandaag")[1].split("Rotterdam — openstaande kansen")[0]
    assert "Geen nieuwe kansen vandaag." in nieuwe_sectie


def test_html_report_toont_winst_en_eigen_inleg_kolommen():
    item = _listing("NEW-1", "Nieuwstraat 1, Rotterdam", "2026-07-09", winst_pm_pp=972.63, eigen_inleg_pp=27_721.05)
    result = RunResult(alle_actief=[item], nieuw_actief=[item])

    html = build_html_report(result, date(2026, 7, 9), "scanner@example.com")

    assert "€973/mnd" in html
    assert "€27.721" in html
    assert "Winst p.p./mnd" in html
    assert "Eigen inleg p.p." in html


def test_html_report_toont_advertentie_oppervlakte_als_primair_en_bag_ter_info():
    item = _listing(
        "NEW-1", "Nieuwstraat 1, Rotterdam", "2026-07-09",
        bag_oppervlakte=115, oppervlakte_advertentie=120, aantal_kamers_mogelijk=6,
    )
    result = RunResult(alle_actief=[item], nieuw_actief=[item])

    html = build_html_report(result, date(2026, 7, 9), "scanner@example.com")

    # Advertentie-m2 (120) is de leidende/getoonde oppervlakte, BAG-m2 (115) staat
    # er alleen nog ter info naast.
    assert "120 m²" in html
    assert "115 m² (BAG, ter info)" in html
    assert "Kamers mogelijk" in html
    # 6 als losse celwaarde, niet toevallig ergens anders in de pagina
    assert '<td style="' in html and ">6</td>" in html


def test_html_report_toont_negatieve_eigen_inleg_met_minteken():
    # Negatief betekent: de lening na ophoging dekt alle kosten - een sterk signaal,
    # dus moet duidelijk als negatief bedrag herkenbaar zijn (niet als een positief
    # bedrag door een wegvallend minteken).
    item = _listing("NEW-1", "Nieuwstraat 1, Rotterdam", "2026-07-09", winst_pm_pp=500.0, eigen_inleg_pp=-12_345.0)
    result = RunResult(alle_actief=[item], nieuw_actief=[item])

    html = build_html_report(result, date(2026, 7, 9), "scanner@example.com")

    assert "-€12.345" in html


def test_html_report_zonder_investeringscijfers_toont_streepje():
    item = _listing("NEW-1", "Nieuwstraat 1, Rotterdam", "2026-07-09")
    result = RunResult(alle_actief=[item], nieuw_actief=[item])

    html = build_html_report(result, date(2026, 7, 9), "scanner@example.com")

    assert "<td" in html  # sanity check dat de tabel gerenderd is
    # geen crash en geen "None" in de output
    assert "None" not in html


def test_html_report_bevat_geen_zelfbewoningsplicht_melding_meer():
    nieuw = _listing("NEW-1", "Nieuwstraat 1, Rotterdam", "2026-07-09")
    result = RunResult(alle_actief=[nieuw], nieuw_actief=[nieuw])

    html = build_html_report(result, date(2026, 7, 9), "scanner@example.com")

    assert "zelfbewoningsplicht" not in html.lower()


def test_text_report_toont_alleen_nieuwe_woningen_in_nieuwe_kansen_blok():
    nieuw = _listing("NEW-1", "Nieuwstraat 1, Rotterdam", "2026-07-09")
    oud = _listing("OLD-1", "Oudstraat 2, Rotterdam", "2026-06-20")
    result = RunResult(alle_actief=[nieuw, oud], nieuw_actief=[nieuw])

    text = build_text_report(result, date(2026, 7, 9), "scanner@example.com")

    nieuwe_sectie = text.split("nieuwe kansen vandaag")[1].split("openstaande kansen")[0]
    assert "Nieuwstraat 1" in nieuwe_sectie
    assert "Oudstraat 2" not in nieuwe_sectie

    openstaande_sectie = text.split("Rotterdam - openstaande kansen")[1]
    assert "Nieuwstraat 1" in openstaande_sectie
    assert "Oudstraat 2" in openstaande_sectie


def test_text_report_bevat_geen_zelfbewoningsplicht_melding_meer():
    nieuw = _listing("NEW-1", "Nieuwstraat 1, Rotterdam", "2026-07-09")
    result = RunResult(alle_actief=[nieuw], nieuw_actief=[nieuw])

    text = build_text_report(result, date(2026, 7, 9), "scanner@example.com")

    assert "zelfbewoningsplicht" not in text.lower()


def test_text_report_zonder_extra_checks_laat_regel_weg():
    zonder_woz = _listing("NEW-1", "Nieuwstraat 1, Rotterdam", "2026-07-09")
    result = RunResult(alle_actief=[zonder_woz], nieuw_actief=[zonder_woz])

    text = build_text_report(result, date(2026, 7, 9), "scanner@example.com")

    assert "nog te checken" not in text


def _den_haag_listing(object_id="DH-1", weergavenaam="Wassenaarseweg 257, Den Haag", eerst_gezien="2026-07-30"):
    return ListingState(
        object_id=object_id,
        url=f"https://example.com/{object_id}",
        weergavenaam=weergavenaam,
        eerst_gezien=eerst_gezien,
        laatst_gezien="2026-07-30",
        status="actief",
        wijknaam="Benoordenhout",
        prijs=595_000,
        oppervlakte_advertentie=218,
        aantal_kamers_mogelijk=8,
        winst_pm_pp=850.0,
        eigen_inleg_pp=15_000.0,
        stad="den_haag",
        check_signalen=[
            "Vanaf 5 bewoners gelden extra geluidsisolatie-eisen (luchtgeluid ≥47 dB, contactgeluid ≤59 dB).",
            "Wijk-quotum: per wijk max. 10% van de woningen als omzetting; check bij de gemeente.",
        ],
    )


def test_html_report_toont_den_haag_in_eigen_sectie():
    rotterdam = _listing("R-1", "Rotterstraat 1, Rotterdam", "2026-07-30")
    den_haag = _den_haag_listing()
    result = RunResult(alle_actief=[rotterdam, den_haag], nieuw_actief=[rotterdam, den_haag])

    html = build_html_report(result, date(2026, 7, 30), "scanner@example.com")

    assert "Den Haag — openstaande kansen (1)" in html
    dh_sectie = html.split("Den Haag — openstaande kansen")[1]
    assert "Wassenaarseweg 257" in dh_sectie
    assert "Benoordenhout" in dh_sectie
    assert "geluidsisolatie" in dh_sectie
    assert "€850/mnd" in dh_sectie  # winst/inleg ook voor Den Haag
    assert "€15.000" in dh_sectie
    # Den Haag-woning hoort niet in de Rotterdam-tabel te staan.
    rotterdam_sectie = html.split("Rotterdam — openstaande kansen")[1].split("Den Haag — openstaande kansen")[0]
    assert "Wassenaarseweg 257" not in rotterdam_sectie


def test_text_report_toont_den_haag_sectie_met_max_bewoners():
    den_haag = _den_haag_listing()
    result = RunResult(alle_actief=[den_haag], nieuw_actief=[den_haag])

    text = build_text_report(result, date(2026, 7, 30), "scanner@example.com")

    assert "Den Haag - openstaande kansen (1)" in text
    assert "max bewoners: 8" in text
    assert "aandachtspunten" in text.lower()

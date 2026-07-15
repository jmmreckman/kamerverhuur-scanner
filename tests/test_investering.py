from rotterdam_scanner.investering import bereken


def test_referentievoorbeeld_matcht_handmatig_doorgerekende_spreadsheet():
    # Koopsom €403.000, 115 m2 BAG (6 kamers), geen opslag - handmatig doorgerekend
    # en bevestigd door de gebruiker vóór dit is gebouwd. Regressietest: als deze ooit
    # faalt is er iets in de kernformule veranderd, niet een afrondingsverschil.
    resultaat = bereken(bag_m2=115, koopsom=403_000)
    assert resultaat is not None
    assert resultaat.aantal_kamers == 6
    assert round(resultaat.taxatie_voor_vergunning, 2) == 352_625.00
    assert round(resultaat.taxatie_na_vergunning, 2) == 521_052.63
    assert round(resultaat.leenbaar_voor_verhoging, 2) == 282_100.00
    assert round(resultaat.leenbaar_na_verhoging, 2) == 416_842.11
    assert round(resultaat.verhoogbaar_met, 2) == 134_742.11
    assert round(resultaat.totale_zelf_in_te_leggen, 2) == 190_184.21
    assert round(resultaat.winst_pm_pp, 2) == 972.63
    assert round(resultaat.eigen_inleg_na_ophoging_pp, 2) == 27_721.05


def test_te_kleine_oppervlakte_geeft_geen_resultaat():
    # Minder dan 18 m2 -> geen enkele studentenkamer mogelijk, geen bruikbare kans.
    assert bereken(bag_m2=15, koopsom=250_000) is None


def test_precies_op_kamer_grens_rondt_naar_beneden_af():
    # 18*5 = 90, dus exact 5 kamers; 90+17=107 zou nog steeds 5 kamers zijn (naar
    # beneden afgerond) totdat de 6e kamer pas bij 108 m2 vol is.
    resultaat_90 = bereken(bag_m2=90, koopsom=300_000)
    resultaat_107 = bereken(bag_m2=107, koopsom=300_000)
    resultaat_108 = bereken(bag_m2=108, koopsom=300_000)
    assert resultaat_90.aantal_kamers == 5
    assert resultaat_107.aantal_kamers == 5
    assert resultaat_108.aantal_kamers == 6


def test_huurprijsopslag_verhoogt_kale_huur_en_dus_de_taxatie_na_vergunning():
    zonder_opslag = bereken(bag_m2=115, koopsom=403_000, opslag_percentage=0.0)
    met_opslag = bereken(bag_m2=115, koopsom=403_000, opslag_percentage=0.05)
    assert met_opslag.taxatie_na_vergunning > zonder_opslag.taxatie_na_vergunning
    # 5% hogere kale huur -> 5% hogere taxatie na vergunning (BAR-formule is lineair
    # in de huur).
    assert round(met_opslag.taxatie_na_vergunning, 2) == round(zonder_opslag.taxatie_na_vergunning * 1.05, 2)
    # Hogere taxatie na vergunning -> meer leenbaar na ophoging -> lagere eigen inleg.
    assert met_opslag.eigen_inleg_na_ophoging_pp < zonder_opslag.eigen_inleg_na_ophoging_pp
    # En hogere kale huur (netto van de hogere rente) -> hogere winst per maand.
    assert met_opslag.winst_pm_pp > zonder_opslag.winst_pm_pp


def test_winst_en_eigen_inleg_worden_door_twee_investeerders_gedeeld():
    resultaat = bereken(bag_m2=115, koopsom=403_000)
    # Los nagerekend zonder de /2: winst zonder deling en eigen inleg zonder deling
    # moeten precies het dubbele zijn van de p.p.-waardes.
    kale_huur_pm = 6 * 550.0
    service_in_pm = 6 * 210.0
    vast_uit_pm = 6 * 100.0
    rente_pm = resultaat.leenbaar_na_verhoging * 0.058 / 12
    winst_totaal = kale_huur_pm + service_in_pm - vast_uit_pm - rente_pm
    assert round(resultaat.winst_pm_pp * 2, 2) == round(winst_totaal, 2)

from rotterdam_scanner.investering import (
    KALE_HUUR_PER_KAMER,
    aantal_kamers_mogelijk,
    bereken,
    bereken_met_aantal_kamers,
)


def test_aantal_kamers_mogelijk_matcht_bereken():
    assert aantal_kamers_mogelijk(115) == 6
    assert aantal_kamers_mogelijk(17) == 0
    assert aantal_kamers_mogelijk(18) == 1


def test_aantal_kamers_mogelijk_werkt_zonder_koopsom_te_kennen():
    # Los bruikbaar zodat de rapporttabel het aantal kamers al kan tonen voordat de
    # vraagprijs bekend is (en dus vóórdat bereken() een resultaat kan geven).
    assert aantal_kamers_mogelijk(115) == bereken(m2=115, koopsom=403_000).aantal_kamers


def test_referentievoorbeeld_matcht_handmatig_doorgerekende_spreadsheet():
    # Koopsom €403.000, 115 m2 BAG (6 kamers), geen opslag - handmatig doorgerekend
    # en bevestigd door de gebruiker vóór dit is gebouwd. Regressietest: als deze ooit
    # faalt is er iets in de kernformule veranderd, niet een afrondingsverschil.
    resultaat = bereken(m2=115, koopsom=403_000)
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
    assert bereken(m2=15, koopsom=250_000) is None


def test_precies_op_kamer_grens_rondt_naar_beneden_af():
    # 18*5 = 90, dus exact 5 kamers; 90+17=107 zou nog steeds 5 kamers zijn (naar
    # beneden afgerond) totdat de 6e kamer pas bij 108 m2 vol is.
    resultaat_90 = bereken(m2=90, koopsom=300_000)
    resultaat_107 = bereken(m2=107, koopsom=300_000)
    resultaat_108 = bereken(m2=108, koopsom=300_000)
    assert resultaat_90.aantal_kamers == 5
    assert resultaat_107.aantal_kamers == 5
    assert resultaat_108.aantal_kamers == 6


def test_huurprijsopslag_verhoogt_kale_huur_en_dus_de_taxatie_na_vergunning():
    zonder_opslag = bereken(m2=115, koopsom=403_000, opslag_percentage=0.0)
    met_opslag = bereken(m2=115, koopsom=403_000, opslag_percentage=0.05)
    assert met_opslag.taxatie_na_vergunning > zonder_opslag.taxatie_na_vergunning
    # 5% hogere kale huur -> 5% hogere taxatie na vergunning (BAR-formule is lineair
    # in de huur).
    assert round(met_opslag.taxatie_na_vergunning, 2) == round(zonder_opslag.taxatie_na_vergunning * 1.05, 2)
    # Hogere taxatie na vergunning -> meer leenbaar na ophoging -> lagere eigen inleg.
    assert met_opslag.eigen_inleg_na_ophoging_pp < zonder_opslag.eigen_inleg_na_ophoging_pp
    # En hogere kale huur (netto van de hogere rente) -> hogere winst per maand.
    assert met_opslag.winst_pm_pp > zonder_opslag.winst_pm_pp


def test_bereken_met_aantal_kamers_zonder_m2_geen_compensatie():
    # Zonder m2 kan de "verloren kamers"-vergelijking niet gemaakt worden, dus geen
    # compensatie - puur het ingevoerde aantal kamers, net als vroeger.
    resultaat = bereken_met_aantal_kamers(3, koopsom=400_000)
    assert resultaat.aantal_kamers == 3


def test_bereken_met_aantal_kamers_compenseert_verloren_kamers():
    # Zuiderterras 63-voorbeeld: 126 m2 -> 7 kamers volgens de 18m2-regel, maar door de
    # raamindeling zijn er maar 3 daadwerkelijk mogelijk. 4 "verloren" kamers -> 50% van
    # hun huurwaarde (4 * 550 * 0.5 = 1100) telt alsnog mee, verdeeld over de 3
    # overgebleven (ruimere) kamers: 3*550 + 1100 = 2750 kale huur/mnd.
    resultaat = bereken_met_aantal_kamers(3, koopsom=400_000, m2=126)
    assert resultaat.aantal_kamers == 3
    kale_huur_pm = 3 * KALE_HUUR_PER_KAMER + 4 * KALE_HUUR_PER_KAMER * 0.5
    assert kale_huur_pm == 2750.0

    zonder_compensatie = bereken_met_aantal_kamers(3, koopsom=400_000)
    # Winst moet hoger zijn mét compensatie dan zonder (meer kale huur, zelfde kosten).
    assert resultaat.winst_pm_pp > zonder_compensatie.winst_pm_pp


def test_bereken_met_aantal_kamers_geen_compensatie_als_niets_verloren_is():
    # Handmatig aantal gelijk aan (of hoger dan) de 18m2-berekening -> geen "verloren"
    # kamers, dus geen compensatie nodig - zelfde uitkomst als zonder m2.
    met_m2 = bereken_met_aantal_kamers(6, koopsom=403_000, m2=115)  # 115/18 = 6, exact gelijk
    zonder_m2 = bereken_met_aantal_kamers(6, koopsom=403_000)
    assert met_m2.winst_pm_pp == zonder_m2.winst_pm_pp


def test_bereken_met_meer_kamers_dan_18m2_regel_geeft_ook_geen_compensatie():
    # Zou niet moeten voorkomen via de UI, maar voor de zekerheid: een hoger handmatig
    # aantal dan de 18m2-regel mag niet tot een NEGATIEVE compensatie (aftrek) leiden.
    met_m2 = bereken_met_aantal_kamers(8, koopsom=403_000, m2=115)  # 115/18 = 6 < 8
    zonder_m2 = bereken_met_aantal_kamers(8, koopsom=403_000)
    assert met_m2.winst_pm_pp == zonder_m2.winst_pm_pp


def test_bereken_via_m2_geeft_zelfde_resultaat_als_via_aantal_kamers():
    # bereken() (m2-gebaseerd) moet, nu die ook m2 doorgeeft aan
    # bereken_met_aantal_kamers(), exact hetzelfde blijven geven als voorheen (geen
    # "verloren kamers" als het aantal al rechtstreeks uit de m2 is afgeleid).
    via_m2 = bereken(m2=115, koopsom=403_000)
    via_aantal = bereken_met_aantal_kamers(6, koopsom=403_000, m2=115)
    assert via_m2 == via_aantal


def test_winst_en_eigen_inleg_worden_door_twee_investeerders_gedeeld():
    resultaat = bereken(m2=115, koopsom=403_000)
    # Los nagerekend zonder de /2: winst zonder deling en eigen inleg zonder deling
    # moeten precies het dubbele zijn van de p.p.-waardes.
    kale_huur_pm = 6 * 550.0
    service_in_pm = 6 * 210.0
    vast_uit_pm = 6 * 100.0
    rente_pm = resultaat.leenbaar_na_verhoging * 0.058 / 12
    winst_totaal = kale_huur_pm + service_in_pm - vast_uit_pm - rente_pm
    assert round(resultaat.winst_pm_pp * 2, 2) == round(winst_totaal, 2)

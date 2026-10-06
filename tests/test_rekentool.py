"""Regressietests voor de interactieve rekentool (investering.bereken_rekentool),
geverifieerd tegen het handmatig doorgerekende praktijkvoorbeeld uit de PDF
'berekening_Azaleastraat_82B' (koopsom EUR 355.000, 6 kamers, 2 investeerders)."""
from rotterdam_scanner.investering import RekenUitgangspunten, bereken_rekentool

# De exacte uitgangspunten uit de PDF (percentages als fractie).
AZALEASTRAAT = RekenUitgangspunten(
    koopsom=355_000,
    aantal_kamers=6,
    aantal_investeerders=2,
    overdrachtsbelasting=0.08,
    bar=0.076,
    kale_huur_per_kamer=560,
    servicekosten_per_kamer=250,
    vaste_kosten_per_huurder=100,
    kosten_koper_ex_ovb=6_000,
    verbouwkosten=25_000,
    rente=0.059,
    taxatie_verhouding_voor_verhoging=0.875,
    ltv=0.8,
)


def test_azaleastraat_berekende_uitgangspunten():
    r = bereken_rekentool(AZALEASTRAAT)
    assert round(r.kale_huur_pm, 2) == 3_360.00
    assert round(r.service_in_pm, 2) == 1_500.00
    assert round(r.vast_uit_pm, 2) == 600.00
    assert round(r.overdrachtsbelasting_eur, 2) == 28_400.00
    assert round(r.taxatie_voor_vergunning, 2) == 310_625.00
    assert round(r.taxatie_na_vergunning, 2) == 530_526.32
    assert round(r.leenbaar_voor_verhoging, 2) == 248_500.00
    assert round(r.leenbaar_na_verhoging, 2) == 424_421.05
    assert round(r.zelf_in_te_leggen_bij_aankoop, 2) == 106_500.00
    assert round(r.rente_pm_na_verhoging, 2) == 2_086.74
    assert round(r.leegstand_3mnd, 2) == 6_260.21
    assert round(r.totale_zelf_in_te_leggen, 2) == 172_160.21
    assert round(r.verhoogbaar_met, 2) == 175_921.05


def test_azaleastraat_aan_te_tonen_middelen():
    # Financieringsopzet-stijl (zoals de hypotheekadviseur rekent). Handmatig:
    #  in te brengen bij passeren = 355.000 + 28.400 (OVB) + 6.000 (k.k.) - 248.500 = 140.900
    #  financieringslasten verbouwing = 6 x 2.086,74 = 12.520,42
    #  opname liquiditeit na verbouwing = 175.921,05 (verhoogbaar) - 25.000 (verbouw) = 150.921,05
    #  aan te tonen = 140.900 + 12.520,42 + 6.260,21 (3 mnd leegstand) = 159.680,63
    r = bereken_rekentool(AZALEASTRAAT)
    assert round(r.in_te_brengen_bij_passeren, 2) == 140_900.00
    assert round(r.financieringslasten_verbouwing, 2) == 12_520.42
    assert round(r.opname_liquiditeit_na_verbouwing, 2) == 150_921.05
    assert round(r.aan_te_tonen_middelen, 2) == 159_680.63


def test_azaleastraat_icr():
    import dataclasses
    # Vóór ophoging: woninghuur = 17,60/m² × oppervlakte (advertentie). Bij 100 m²:
    #   1.760 huur / (248.500 × 0,059/12 = 1.221,79) rente voor = 1,44
    # Ná ophoging: 3.360 volle kamerhuur / (424.421,05 × 0,059/12 = 2.086,74) rente na = 1,61
    r = bereken_rekentool(dataclasses.replace(AZALEASTRAAT, oppervlakte_m2=100))
    assert round(r.wwsz_huur_gezin, 2) == 1760.00   # 100 m² × €17,60 = WWSZ-gezinshuur
    assert round(r.icr_voor_ophoging, 2) == 1.44
    assert round(r.icr_na_ophoging, 2) == 1.61


def test_icr_voor_none_zonder_oppervlakte():
    # Zonder bekende oppervlakte (default 0) is de ICR vóór ophoging niet te bepalen;
    # de ICR ná ophoging (op de kamerhuur) wel.
    r = bereken_rekentool(AZALEASTRAAT)
    assert r.icr_voor_ophoging is None
    assert round(r.icr_na_ophoging, 2) == 1.61


def test_icr_none_bij_lening_nul():
    # Guard: geen deling door nul als er geen lening (en dus geen rente) is.
    r = bereken_rekentool(RekenUitgangspunten(koopsom=0, aantal_kamers=0, bar=0.076, oppervlakte_m2=100))
    assert r.icr_voor_ophoging is None
    assert r.icr_na_ophoging is None


def test_aan_te_tonen_negeert_verbouwkosten_maar_opname_niet():
    # De verbouwkosten lopen via het bouwdepot: ze veranderen "aan te tonen middelen"
    # NIET, maar verlagen wel de opname liquiditeit na verbouwing met hetzelfde bedrag.
    laag = bereken_rekentool(RekenUitgangspunten(koopsom=355_000, aantal_kamers=6, verbouwkosten=25_000))
    hoog = bereken_rekentool(RekenUitgangspunten(koopsom=355_000, aantal_kamers=6, verbouwkosten=60_000))
    assert round(laag.aan_te_tonen_middelen, 2) == round(hoog.aan_te_tonen_middelen, 2)
    assert round(laag.opname_liquiditeit_na_verbouwing - hoog.opname_liquiditeit_na_verbouwing, 2) == 35_000.00


def test_azaleastraat_belangrijke_resultaten():
    r = bereken_rekentool(AZALEASTRAAT)
    assert round(r.winst_pm_pp, 2) == 1_086.63
    assert round(r.eigen_inleg_voor_ophoging_totaal, 2) == 172_160.21
    assert round(r.eigen_inleg_na_ophoging_pp, 2) == -1_880.42
    # Rendement = winst/jaar p.p. gedeeld door eigen inleg na ophoging (negatief:
    # je hebt na de ophoging meer eruit gehaald dan je erin liet zitten).
    assert round(r.rendement * 100, 2) == -693.44


def test_standaardaannames_matchen_de_moduleconstanten():
    # Zonder overrides gebruikt de rekentool exact de scanner-uitgangspunten, zodat
    # de standaarduitkomst gelijk is aan wat de kaart voor die woning laat zien.
    from rotterdam_scanner.investering import bereken_met_aantal_kamers

    u = RekenUitgangspunten(koopsom=403_000, aantal_kamers=6)
    r = bereken_rekentool(u)
    ref = bereken_met_aantal_kamers(6, koopsom=403_000)
    assert round(r.winst_pm_pp, 2) == round(ref.winst_pm_pp, 2)
    assert round(r.eigen_inleg_na_ophoging_pp, 2) == round(ref.eigen_inleg_na_ophoging_pp, 2)


def test_rendement_none_bij_eigen_inleg_nul():
    # Guard: geen deling door nul als de eigen inleg na ophoging precies 0 uitkomt.
    u = RekenUitgangspunten(koopsom=0, aantal_kamers=0, kosten_koper_ex_ovb=0, verbouwkosten=0)
    r = bereken_rekentool(u)
    assert r.eigen_inleg_na_ophoging_pp == 0
    assert r.rendement is None

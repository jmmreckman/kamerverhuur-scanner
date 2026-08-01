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

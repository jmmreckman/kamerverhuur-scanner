from decimal import Decimal

from kamerverhuur_scanner import huuroverzicht as ho


def _regel(kale, service=0, naam="X", kamer="K", handmatig=False, regel_id=0):
    return ho.HuurRegel(
        kamer=kamer, naam=naam, kale=Decimal(str(kale)),
        servicekosten=Decimal(str(service)), handmatig=handmatig, regel_id=regel_id,
    )


def test_regel_totaal():
    r = _regel(350, 50)
    assert r.totaal == Decimal("400")


def test_pand_totalen_en_netto():
    p = ho.PandHuur(
        slug="a", naam="A",
        regels=[_regel(300, 40), _regel(350, 60)],
        rente=Decimal("200"), last=Decimal("500"), aantal_eigenaren=1,
    )
    assert p.kale_totaal == Decimal("650")
    assert p.service_totaal == Decimal("100")
    assert p.totaal == Decimal("750")
    # netto = kale - rente (servicekosten tellen NIET mee)
    assert p.netto == Decimal("450")
    assert p.netto_eigen == Decimal("450")  # 1 eigenaar: geen deling
    # ICR = kale / rente
    assert p.icr == Decimal("3.25")
    assert p.gedeeld is False


def test_gedeeld_pand_deelt_netto_maar_niet_icr():
    p = ho.PandHuur(
        slug="b", naam="B", regels=[_regel(600)],
        rente=Decimal("300"), last=None, aantal_eigenaren=2,
    )
    assert p.gedeeld is True
    assert p.netto == Decimal("300")          # volledig pand
    assert p.netto_eigen == Decimal("150.00")  # jouw helft
    assert p.icr == Decimal("2.00")            # ratio verandert niet door delen


def test_geen_rente_geeft_geen_netto_of_icr():
    p = ho.PandHuur(slug="c", naam="C", regels=[_regel(500)], rente=None, last=None)
    assert p.netto is None
    assert p.netto_eigen is None
    assert p.icr is None


def test_nul_rente_geeft_geen_icr():
    p = ho.PandHuur(slug="d", naam="D", regels=[_regel(500)], rente=Decimal("0"), last=None)
    assert p.icr is None
    assert p.netto == Decimal("500")  # kale - 0


def test_totaliseer_mengt_panden_met_en_zonder_rente():
    p1 = ho.PandHuur(slug="a", naam="A", regels=[_regel(600, 50)], rente=Decimal("300"), last=Decimal("450"), aantal_eigenaren=2)
    p2 = ho.PandHuur(slug="b", naam="B", regels=[_regel(400, 30)], rente=Decimal("200"), last=Decimal("260"), aantal_eigenaren=1)
    p3 = ho.PandHuur(slug="c", naam="C", regels=[_regel(500)], rente=None, last=None, aantal_eigenaren=1)
    t = ho.totaliseer([p1, p2, p3])

    assert t.kale == Decimal("1500")       # 600 + 400 + 500
    assert t.service == Decimal("80")
    assert t.totaal == Decimal("1580")
    assert t.rente == Decimal("500")       # alleen p1 + p2
    assert t.last == Decimal("710")
    # netto volledig: (600-300) + (400-200) = 500 ; p3 telt niet mee (geen rente)
    assert t.netto_vol == Decimal("500")
    # jouw aandeel: 300/2 + 200/1 = 150 + 200 = 350
    assert t.netto_eigen == Decimal("350.00")
    # portefeuille-ICR = kale van panden MET rente / som rente = (600+400)/500 = 2.00
    assert t.icr == Decimal("2.00")
    assert t.panden_met_rente == 2


def test_totaliseer_zonder_enige_rente():
    p = ho.PandHuur(slug="x", naam="X", regels=[_regel(500)], rente=None, last=None)
    t = ho.totaliseer([p])
    assert t.icr is None
    assert t.netto_vol is None
    assert t.netto_eigen is None
    assert t.rente == Decimal("0")


def test_lege_portefeuille():
    t = ho.totaliseer([])
    assert t.kale == Decimal("0")
    assert t.icr is None
    assert t.netto_vol is None

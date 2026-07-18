"""Tests voor de advertentietekst-generator (webapp/ads.py): titel/
beschrijving voor Kamernet e.d. - gebruikt de apart ingevulde advertentie-
velden (prijs, oppervlakte, beschikbaarheid, borg) als die er zijn, anders
een terugval op de gewone huur/borg of een invulplekje."""
from decimal import Decimal

from kamerverhuur_scanner.models import Pand, Tenant
from webapp import ads


def _pand(**overrides) -> Pand:
    basis = dict(
        slug="mahoniestraat", naam="Mahoniestraat 15", google_sheet_id="x",
        google_sheet_worksheet="Huurders", history_worksheet="Historie",
        google_drive_folder_id=None, bunq_rekening_iban="NL81BUNQ2163127125",
    )
    basis.update(overrides)
    return Pand(**basis)


def _kamer(**overrides) -> Tenant:
    basis = dict(row_index=2, naam="", kamer="1", verwacht_bedrag=Decimal("650.00"))
    basis.update(overrides)
    return Tenant(**basis)


# --- weergave_prijs ---


def test_weergave_prijs_valt_terug_op_verwacht_bedrag_zonder_advertentieprijs():
    assert ads.weergave_prijs(_kamer(verwacht_bedrag=Decimal("650.00"))) == Decimal("650.00")


def test_weergave_prijs_gebruikt_advertentieprijs_indien_ingevuld():
    kamer = _kamer(verwacht_bedrag=Decimal("650.00"), advertentie_prijs=Decimal("725.00"))
    assert ads.weergave_prijs(kamer) == Decimal("725.00")


# --- genereer_advertentie ---


def test_genereer_advertentie_zonder_advertentievelden_toont_invulplekken():
    advertentie = ads.genereer_advertentie(_pand(), _kamer(verwacht_bedrag=Decimal("650.00")))
    assert "EUR 650" in advertentie["titel"]
    assert "EUR 650.00" in advertentie["beschrijving"]
    assert "[vul datum in]" in advertentie["beschrijving"]
    assert "Oppervlakte" not in advertentie["beschrijving"]
    assert "Waarborgsom" not in advertentie["beschrijving"]


def test_genereer_advertentie_gebruikt_advertentieprijs_in_titel_en_tekst():
    kamer = _kamer(verwacht_bedrag=Decimal("650.00"), advertentie_prijs=Decimal("725.00"))
    advertentie = ads.genereer_advertentie(_pand(), kamer)
    assert "EUR 725" in advertentie["titel"]
    assert "EUR 725.00" in advertentie["beschrijving"]
    assert "650" not in advertentie["titel"]


def test_genereer_advertentie_toont_oppervlakte_indien_ingevuld():
    kamer = _kamer(advertentie_oppervlakte="18 m²")
    advertentie = ads.genereer_advertentie(_pand(), kamer)
    assert "Oppervlakte: 18 m²" in advertentie["beschrijving"]


def test_genereer_advertentie_toont_beschikbaar_per_en_tot():
    kamer = _kamer(advertentie_beschikbaar_per="01-09-2026", advertentie_beschikbaar_tot="01-07-2027")
    advertentie = ads.genereer_advertentie(_pand(), kamer)
    assert "Beschikbaar per: 01-09-2026 t/m 01-07-2027" in advertentie["beschrijving"]


def test_genereer_advertentie_beschikbaar_per_zonder_tot_geen_t_m():
    kamer = _kamer(advertentie_beschikbaar_per="01-09-2026")
    advertentie = ads.genereer_advertentie(_pand(), kamer)
    assert "Beschikbaar per: 01-09-2026\n" in advertentie["beschrijving"]
    assert "t/m" not in advertentie["beschrijving"]


def test_genereer_advertentie_toont_advertentieborg_indien_ingevuld():
    kamer = _kamer(advertentie_borg=Decimal("1000.00"), borg_bedrag=Decimal("500.00"))
    advertentie = ads.genereer_advertentie(_pand(), kamer)
    assert "Waarborgsom: EUR 1000.00" in advertentie["beschrijving"]


def test_genereer_advertentie_valt_terug_op_borg_bedrag_zonder_advertentieborg():
    kamer = _kamer(borg_bedrag=Decimal("500.00"))
    advertentie = ads.genereer_advertentie(_pand(), kamer)
    assert "Waarborgsom: EUR 500.00" in advertentie["beschrijving"]

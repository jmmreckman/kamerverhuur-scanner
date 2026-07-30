from datetime import date

from rotterdam_scanner.handmatig import (
    HandmatigeRegelError,
    listing_state_naar_funda_listing,
    parse_bestand,
    parse_funda_tekstdump,
    parse_regel,
    parse_regels,
)
from rotterdam_scanner.state import ListingState


def test_parse_regel_met_toevoeging_en_zonder_link():
    listing = parse_regel("3073KJ 47A")
    assert listing.postcode == "3073KJ"
    assert listing.huisnummer == "47"
    assert listing.toevoeging == "A"
    assert listing.object_id == "3073KJ-47A"
    assert listing.url.startswith("https://www.google.com/search?q=")
    assert "3073KJ" in listing.url and "47A" in listing.url


def test_parse_regel_met_koppelteken_geeft_zelfde_resultaat_als_zonder():
    met_koppelteken = parse_regel("3073KJ 47-A")
    zonder_koppelteken = parse_regel("3073KJ 47A")
    assert met_koppelteken.huisnummer == zonder_koppelteken.huisnummer == "47"
    assert met_koppelteken.toevoeging == zonder_koppelteken.toevoeging == "A"
    assert met_koppelteken.object_id == zonder_koppelteken.object_id


def test_parse_regel_zonder_toevoeging_met_link():
    listing = parse_regel("3078CN 44 https://www.funda.nl/detail/koop/rotterdam/huis-vredehagen-44/12345678/")
    assert listing.huisnummer == "44"
    assert listing.toevoeging == ""
    assert listing.url == "https://www.funda.nl/detail/koop/rotterdam/huis-vredehagen-44/12345678/"


def test_parse_regel_postcode_met_spatie():
    listing = parse_regel("3078 CN 44")
    assert listing.postcode == "3078CN"


def test_parse_regel_onherkenbaar_geeft_duidelijke_fout():
    try:
        parse_regel("Hillevliet 47A")
    except HandmatigeRegelError as exc:
        assert "kon niet gelezen worden" in str(exc)
    else:
        raise AssertionError("had een HandmatigeRegelError moeten geven")


def test_parse_regels_slaat_lege_en_commentaarregels_over():
    listings, fouten = parse_regels(["", "  ", "# commentaar", "3073KJ 47A"])
    assert len(listings) == 1
    assert fouten == []


def test_parse_regels_verzamelt_fouten_zonder_te_stoppen():
    listings, fouten = parse_regels(["3073KJ 47A", "onzin regel", "3078CN 44"])
    assert len(listings) == 2
    assert len(fouten) == 1
    assert "Regel 2" in fouten[0]


_VOORBEELD_KAART = """
Hillevliet 47-A
3073 KJ Rotterdam
€ 260.000 k.k.
97 m²
3
E

Groene Hilledijk 378-B
3075 ED Rotterdam
€ 400.000 k.k.
124 m²
3
C
"""


def test_parse_funda_tekstdump_herkent_adres_postcode_en_prijs():
    listings, fouten = parse_funda_tekstdump(_VOORBEELD_KAART)
    assert fouten == []
    by_id = {l.object_id: l for l in listings}
    assert by_id["3073KJ-47A"].straatnaam == "Hillevliet"
    assert by_id["3073KJ-47A"].huisnummer == "47"
    assert by_id["3073KJ-47A"].toevoeging == "A"
    assert by_id["3073KJ-47A"].woonplaats == "Rotterdam"
    assert by_id["3073KJ-47A"].prijs == 260000
    assert by_id["3073KJ-47A"].oppervlakte_advertentie == 97
    assert by_id["3075ED-378B"].prijs == 400000
    assert by_id["3075ED-378B"].oppervlakte_advertentie == 124


def test_parse_funda_tekstdump_pakt_woonoppervlakte_niet_perceeloppervlakte():
    # Funda toont bij een huis twee "X m²"-regels: eerst wonen, dan perceel (bv.
    # "88 m²" wonen, "137 m²" perceel) - de tweede (grotere) mag nooit als
    # woonoppervlak gebruikt worden, dat zou de kamerberekening flink vertekenen.
    tekst = (
        "Murraystraat 18\n3195 VJ Pernis Rotterdam\n€ 350.000 k.k.\n88 m²\n137 m²\n3\nC\n"
    )
    listings, fouten = parse_funda_tekstdump(tekst)
    assert fouten == []
    assert len(listings) == 1
    assert listings[0].oppervlakte_advertentie == 88


def test_parse_funda_tekstdump_zonder_oppervlakteregel_geeft_none():
    tekst = "Vredehagen 44\n3078 CN Rotterdam\n€ 635.000 k.k.\n4\nA\n"
    listings, fouten = parse_funda_tekstdump(tekst)
    assert fouten == []
    assert listings[0].oppervlakte_advertentie is None


def test_parse_funda_tekstdump_herkent_plaats_met_provincie_afkorting():
    # Regressietest: funda voegt bij plaatsnamen die in meerdere provincies
    # voorkomen (bv. Rozenburg) een provincie-afkorting tussen haakjes toe -
    # "3181 WX Rozenburg (ZH)" i.p.v. gewoon "3181 WX Rozenburg". Zonder
    # rekening te houden met die haakjes werd de postcode-regel he-le-maal
    # niet herkend (geen match, geen fout) en kwam er 0 adressen uit een
    # geplakte tekst die er duidelijk 1 bevatte. Ook de lege regel (spatie)
    # tussen adres en postcode-regel, zoals mobiel kopiëren/plakken die vaak
    # meebrengt, moet genegeerd worden - _bepaal_eerst_gezien e.d. testen dat
    # elders al voor "gewone" lege regels.
    tekst = "Tulpenstraat 3 \n \n3181 WX Rozenburg (ZH)\n€ 330.000 k.k.\n75 m²\n143 m²\n3\nD\n"
    listings, fouten = parse_funda_tekstdump(tekst)
    assert fouten == []
    assert len(listings) == 1
    assert listings[0].object_id == "3181WX-3"
    assert listings[0].woonplaats == "Rozenburg"
    assert listings[0].prijs == 330000
    assert listings[0].oppervlakte_advertentie == 75


def test_parse_funda_tekstdump_werkt_zonder_lege_regel_tussen_woningen():
    tekst = (
        "Vredehagen 44  \n3078 CN Rotterdam\n€ 635.000 k.k.\n163 m²\n4\nA\n"
        "Jan Pettersonstraat 15  \n3077 MN Rotterdam\n€ 625.000 k.k.\n187 m²\n3\nA\n"
    )
    listings, fouten = parse_funda_tekstdump(tekst)
    assert fouten == []
    assert {l.object_id for l in listings} == {"3078CN-44", "3077MN-15"}


def test_parse_funda_tekstdump_negeert_niet_adresachtige_tekst():
    listings, fouten = parse_funda_tekstdump("Zomaar wat tekst zonder postcodes.\nNog een regel.")
    assert listings == []
    assert fouten == []


def test_parse_funda_tekstdump_meldt_postcode_zonder_herkenbaar_adres():
    listings, fouten = parse_funda_tekstdump("Blikvanger\n3073 KJ Rotterdam\n€ 260.000 k.k.\n")
    assert listings == []
    assert len(fouten) == 1


def test_parse_bestand_herkent_tekstdump_automatisch():
    listings, fouten = parse_bestand(_VOORBEELD_KAART)
    assert len(listings) == 2
    assert fouten == []


def test_parse_bestand_valt_terug_op_simpel_formaat():
    listings, fouten = parse_bestand("3073KJ 47A\n3078CN 44\n")
    assert len(listings) == 2
    assert fouten == []


def test_parse_regels_dedupliceert_op_object_id():
    listings, _ = parse_regels(["3073KJ 47A", "3073kj 47a"])
    assert len(listings) == 1


def test_parse_funda_tekstdump_herkent_sinds_weken():
    tekst = "Vredehagen 44\n3078 CN Rotterdam\n€ 635.000 k.k.\n163 m²\nSinds 2 weken\n"
    listings, _ = parse_funda_tekstdump(tekst, vandaag=date(2026, 7, 5))
    assert listings[0].eerst_gezien_override == date(2026, 6, 21)


def test_parse_funda_tekstdump_herkent_sinds_maanden():
    tekst = "Vredehagen 44\n3078 CN Rotterdam\n€ 635.000 k.k.\nSinds 3 maanden\n"
    listings, _ = parse_funda_tekstdump(tekst, vandaag=date(2026, 7, 5))
    assert listings[0].eerst_gezien_override == date(2026, 4, 6)


def test_parse_funda_tekstdump_herkent_exacte_datum_in_het_verleden():
    tekst = "Vredehagen 44\n3078 CN Rotterdam\n€ 635.000 k.k.\nVrijdag 3 juli\n"
    listings, _ = parse_funda_tekstdump(tekst, vandaag=date(2026, 7, 5))
    assert listings[0].eerst_gezien_override == date(2026, 7, 3)


def test_parse_funda_tekstdump_exacte_datum_in_de_toekomst_wordt_vorig_jaar():
    tekst = "Vredehagen 44\n3078 CN Rotterdam\n€ 635.000 k.k.\nMaandag 10 augustus\n"
    listings, _ = parse_funda_tekstdump(tekst, vandaag=date(2026, 7, 5))
    assert listings[0].eerst_gezien_override == date(2025, 8, 10)


def test_parse_funda_tekstdump_zonder_datumaanduiding_geeft_geen_override():
    tekst = "Vredehagen 44\n3078 CN Rotterdam\n€ 635.000 k.k.\nNieuw\n"
    listings, _ = parse_funda_tekstdump(tekst, vandaag=date(2026, 7, 5))
    assert listings[0].eerst_gezien_override is None


def test_parse_funda_tekstdump_datum_loopt_niet_over_naar_volgende_woning():
    tekst = (
        "Vredehagen 44\n3078 CN Rotterdam\n€ 635.000 k.k.\n"
        "Jan Pettersonstraat 15\n3077 MN Rotterdam\n€ 625.000 k.k.\nSinds 2 weken\n"
    )
    listings, _ = parse_funda_tekstdump(tekst, vandaag=date(2026, 7, 5))
    by_id = {l.object_id: l for l in listings}
    assert by_id["3078CN-44"].eerst_gezien_override is None
    assert by_id["3077MN-15"].eerst_gezien_override == date(2026, 6, 21)


def _afgevallen_state(object_id="3073KJ-47A", straatnaam="Hillevliet", url="https://example.com/x"):
    return ListingState(
        object_id=object_id,
        url=url,
        weergavenaam=f"{straatnaam} 47A, Rotterdam",
        eerst_gezien="2026-06-01",
        laatst_gezien="2026-07-01",
        status="afgevallen",
        straatnaam=straatnaam,
        huisnummer="47A",
        afvalreden="Ligt binnen 50 meter van een bestaande kamerverhuurvergunning.",
    )


def test_listing_state_naar_funda_listing_met_toevoeging():
    listing = listing_state_naar_funda_listing(_afgevallen_state())
    assert listing.postcode == "3073KJ"
    assert listing.huisnummer == "47"
    assert listing.toevoeging == "A"
    assert listing.object_id == "3073KJ-47A"
    assert listing.url == "https://example.com/x"


def test_listing_state_naar_funda_listing_zonder_toevoeging():
    listing = listing_state_naar_funda_listing(_afgevallen_state(object_id="3078CN-44"))
    assert listing.huisnummer == "44"
    assert listing.toevoeging == ""


def test_listing_state_naar_funda_listing_onherkende_id_geeft_none():
    assert listing_state_naar_funda_listing(_afgevallen_state(object_id="niet-een-postcode")) is None


# --- Straat-adreslijst zonder postcode (bv. de lijst van Wout) ---


def test_parse_bestand_herkent_straat_adres_zonder_postcode():
    from rotterdam_scanner.handmatig import parse_bestand

    tekst = "Wassenaarseweg 257, Den Haag\nWeimarstraat 70 A, Den Haag\nLoosduinseweg 673 B, Den Haag"
    listings, fouten = parse_bestand(tekst)
    assert fouten == []
    assert len(listings) == 3
    eerste = listings[0]
    assert eerste.straatnaam == "Wassenaarseweg"
    assert eerste.huisnummer == "257"
    assert eerste.toevoeging == ""
    assert eerste.woonplaats == "Den Haag"
    assert eerste.postcode is None
    assert eerste.adres_bekend is True
    tweede = next(l for l in listings if l.huisnummer == "70")
    assert tweede.toevoeging == "A"


def test_parse_adres_regel_negeert_postcode_regels():
    # Een "POSTCODE HUISNUMMER"-regel (geen komma+plaats) mag NIET als straat-adres matchen.
    from rotterdam_scanner.handmatig import parse_adres_regels

    listings, _fouten = parse_adres_regels(["3073KJ 47A"])
    assert listings == []


def test_parse_adres_regel_leest_optionele_m2_achter_pipe():
    from rotterdam_scanner.handmatig import parse_adres_regel

    listing = parse_adres_regel("Wassenaarseweg 257, Den Haag | 218")
    assert listing.straatnaam == "Wassenaarseweg"
    assert listing.huisnummer == "257"
    assert listing.woonplaats == "Den Haag"
    assert listing.oppervlakte_advertentie == 218


def test_parse_adres_regel_zonder_m2_geeft_none():
    from rotterdam_scanner.handmatig import parse_adres_regel

    listing = parse_adres_regel("Wassenaarseweg 257, Den Haag")
    assert listing.oppervlakte_advertentie is None


def test_parse_adres_regel_leest_m2_en_prijs():
    from rotterdam_scanner.handmatig import parse_adres_regel

    listing = parse_adres_regel("Wassenaarseweg 257, Den Haag | 218 | 595000")
    assert listing.oppervlakte_advertentie == 218
    assert listing.prijs == 595000


def test_parse_adres_regel_prijs_met_opmaak_en_omgekeerde_volgorde():
    from rotterdam_scanner.handmatig import parse_adres_regel

    # € en duizendtalscheiding, en prijs vóór de m² (volgorde-onafhankelijk).
    listing = parse_adres_regel("Weimarstraat 70 A, Den Haag | € 595.000 | 203 m²")
    assert listing.prijs == 595000
    assert listing.oppervlakte_advertentie == 203

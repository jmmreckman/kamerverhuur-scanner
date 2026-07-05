from rotterdam_scanner.handmatig import HandmatigeRegelError, parse_regel, parse_regels


def test_parse_regel_met_toevoeging_en_zonder_link():
    listing = parse_regel("3073KJ 47A")
    assert listing.postcode == "3073KJ"
    assert listing.huisnummer == "47"
    assert listing.toevoeging == "A"
    assert listing.object_id == "3073KJ-47A"
    assert listing.url.startswith("https://www.funda.nl/")


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


def test_parse_regels_dedupliceert_op_object_id():
    listings, _ = parse_regels(["3073KJ 47A", "3073kj 47a"])
    assert len(listings) == 1

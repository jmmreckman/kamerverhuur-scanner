from rotterdam_scanner.funda_mail import extract_listings_from_email_body, parse_funda_link


def test_parse_funda_link_nieuw_schema():
    url = "https://www.funda.nl/detail/koop/rotterdam/huis-kruisplein-10/43334567/"
    listing = parse_funda_link(url)
    assert listing is not None
    assert listing.object_id == "43334567"
    assert listing.straatnaam == "Kruisplein"
    assert listing.huisnummer == "10"
    assert listing.woonplaats == "Rotterdam"
    assert listing.adres_bekend


def test_parse_funda_link_oud_schema():
    url = "https://www.funda.nl/koop/rotterdam/huis-43334567-nieuwe-binnenweg-100a/"
    listing = parse_funda_link(url)
    assert listing is not None
    assert listing.object_id == "43334567"
    assert listing.straatnaam == "Nieuwe Binnenweg"
    assert listing.huisnummer == "100a"


def test_parse_funda_link_onherkenbare_url_geeft_none():
    assert parse_funda_link("https://www.funda.nl/makelaars/") is None
    assert parse_funda_link("https://www.example.com/detail/koop/rotterdam/huis-x-1/1/") is None


def test_extract_listings_dedupliceert_op_object_id():
    body = """
    <html>
      <a href="https://www.funda.nl/detail/koop/rotterdam/huis-kruisplein-10/1/">bekijk</a>
      <a href="https://www.funda.nl/detail/koop/rotterdam/huis-kruisplein-10/1/">bekijk nogmaals</a>
      <a href="https://www.funda.nl/detail/koop/rotterdam/huis-west-kruiskade-25/2/">ander huis</a>
      <a href="https://www.funda.nl/makelaars/">geen woning-link</a>
    </html>
    """
    listings = extract_listings_from_email_body(body)
    ids = sorted(listing.object_id for listing in listings)
    assert ids == ["1", "2"]


def test_extract_listings_lege_body():
    assert extract_listings_from_email_body("") == []

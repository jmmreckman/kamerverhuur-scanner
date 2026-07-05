from rotterdam_scanner.funda_mail import extract_listings_from_email_body, parse_funda_link, scan_email_body


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


def test_scan_email_body_haalt_prijs_op_uit_venster_na_link():
    body = """
    <a href="https://www.funda.nl/detail/koop/rotterdam/huis-kruisplein-10/1/">Kruisplein 10</a>
    <span>€ 375.000 k.k.</span>
    """
    scan = scan_email_body(body)
    assert len(scan.listings) == 1
    assert scan.listings[0].prijs == 375000
    assert scan.status_updates == {}


def test_scan_email_body_venster_loopt_niet_over_naar_volgende_woning():
    body = """
    <a href="https://www.funda.nl/detail/koop/rotterdam/huis-kruisplein-10/1/">Kruisplein 10</a>
    <span>€ 375.000 k.k.</span>
    <a href="https://www.funda.nl/detail/koop/rotterdam/huis-west-kruiskade-25/2/">West-Kruiskade 25</a>
    Onder bod
    """
    scan = scan_email_body(body)
    listings_by_id = {listing.object_id: listing for listing in scan.listings}

    assert listings_by_id["1"].prijs == 375000
    assert "1" not in scan.status_updates
    assert scan.status_updates == {"2": "onder bod"}


def test_scan_email_body_detecteert_onder_bod_en_sluit_uit_van_nieuwe_listings():
    body = """
    <a href="https://www.funda.nl/detail/koop/rotterdam/huis-kruisplein-10/1/">Kruisplein 10</a>
    <span class="label">Onder bod</span>
    """
    scan = scan_email_body(body)
    assert scan.listings == []
    assert scan.status_updates == {"1": "onder bod"}


def test_scan_email_body_detecteert_verkocht():
    body = '<a href="https://www.funda.nl/detail/koop/rotterdam/huis-kruisplein-10/1/">x</a> Verkocht'
    scan = scan_email_body(body)
    assert scan.status_updates == {"1": "verkocht"}


def test_scan_email_body_zonder_prijs_of_status_laat_prijs_leeg():
    body = '<a href="https://www.funda.nl/detail/koop/rotterdam/huis-kruisplein-10/1/">Kruisplein 10</a>'
    scan = scan_email_body(body)
    assert len(scan.listings) == 1
    assert scan.listings[0].prijs is None
    assert scan.status_updates == {}

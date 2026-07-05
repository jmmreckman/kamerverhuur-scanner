from unittest.mock import MagicMock, patch

from rotterdam_scanner.config import Config
from rotterdam_scanner.funda_mail import (
    extract_listings_from_email_body,
    fetch_verwijder_commandos,
    parse_funda_link,
    scan_email_body,
)


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


def test_scan_email_body_venster_loopt_niet_over_naar_volgende_woning():
    body = """
    <a href="https://www.funda.nl/detail/koop/rotterdam/huis-kruisplein-10/1/">Kruisplein 10</a>
    <span>€ 375.000 k.k.</span>
    <a href="https://www.funda.nl/detail/koop/rotterdam/huis-west-kruiskade-25/2/">West-Kruiskade 25</a>
    <span>€ 250.000 k.k.</span>
    """
    scan = scan_email_body(body)
    listings_by_id = {listing.object_id: listing for listing in scan.listings}

    assert listings_by_id["1"].prijs == 375000
    assert listings_by_id["2"].prijs == 250000


def test_scan_email_body_zonder_prijs_laat_prijs_leeg():
    body = '<a href="https://www.funda.nl/detail/koop/rotterdam/huis-kruisplein-10/1/">Kruisplein 10</a>'
    scan = scan_email_body(body)
    assert len(scan.listings) == 1
    assert scan.listings[0].prijs is None


def _config():
    return Config(
        gmail_address="scanner@example.com",
        gmail_app_password="dummy",
        report_to=["jmmreckman@example.com"],
        funda_mail_folder="INBOX",
        listing_expiry_days=30,
        opkoopbescherming_woz_grens=470_000,
        state_path="/tmp/onbelangrijk-voor-deze-test.json",
    )


def _mock_imap(search_result, fetch_results):
    imap = MagicMock()
    imap.__enter__.return_value = imap
    imap.search.return_value = ("OK", search_result)
    imap.fetch.side_effect = lambda msg_id, *_args: fetch_results[msg_id]
    return imap


def test_fetch_verwijder_commandos_parseert_object_id_uit_onderwerp():
    fetch_results = {
        b"1": ("OK", [(b"1 (...)", b"Subject: Verwijder 43334567\r\n\r\n")]),
        b"2": ("OK", [(b"2 (...)", b"Subject: Verwijder 99999999 - Kruisplein 10\r\n\r\n")]),
    }
    imap = _mock_imap([b"1 2"], fetch_results)

    with patch("rotterdam_scanner.funda_mail.imaplib.IMAP4_SSL", return_value=imap):
        object_ids = fetch_verwijder_commandos(_config())

    assert object_ids == {"43334567", "99999999"}


def test_fetch_verwijder_commandos_negeert_onherkenbaar_onderwerp():
    fetch_results = {b"1": ("OK", [(b"1 (...)", b"Subject: Verwijderd door iemand anders\r\n\r\n")])}
    imap = _mock_imap([b"1"], fetch_results)

    with patch("rotterdam_scanner.funda_mail.imaplib.IMAP4_SSL", return_value=imap):
        object_ids = fetch_verwijder_commandos(_config())

    assert object_ids == set()


def test_fetch_verwijder_commandos_zonder_treffers():
    imap = _mock_imap([b""], {})

    with patch("rotterdam_scanner.funda_mail.imaplib.IMAP4_SSL", return_value=imap):
        object_ids = fetch_verwijder_commandos(_config())

    assert object_ids == set()

from unittest.mock import MagicMock, patch

from rotterdam_scanner.config import Config
from rotterdam_scanner.funda_mail import fetch_verwijder_commandos, scan_email_body

# Vereenvoudigde versie van de structuur die in een echte funda-alertmail zit (getest
# tegen een echte .eml): een link met een geneste <span> die het adres bevat, gevolgd
# door aparte <span>-elementen voor postcode+plaats en prijs.
_KAART_TEMPLATE = """
<a target="_blank" href="{url}" rel="noopener">
  <span style="color:#0071b3;">{adres}</span>
</a>
<span>{postcode} {plaats}</span>
<span>€ {prijs} k.k.</span>
<span>{oppervlakte} m² • {kamers} kamers</span>
"""


def _kaart(url="https://links.funda.nl/s/c/token1/hash1/22", adres="Hillevliet 47 A",
           postcode="3073 KJ", plaats="Rotterdam", prijs="260.000", oppervlakte="97", kamers="4"):
    return _KAART_TEMPLATE.format(
        url=url, adres=adres, postcode=postcode, plaats=plaats, prijs=prijs, oppervlakte=oppervlakte, kamers=kamers
    )


def test_scan_email_body_herkent_adres_postcode_en_prijs():
    scan = scan_email_body(_kaart())
    assert len(scan.listings) == 1
    listing = scan.listings[0]
    assert listing.straatnaam == "Hillevliet"
    assert listing.huisnummer == "47"
    assert listing.toevoeging == "A"
    assert listing.postcode == "3073KJ"
    assert listing.woonplaats == "Rotterdam"
    assert listing.prijs == 260000
    assert listing.object_id == "3073KJ-47A"
    assert listing.adres_bekend
    assert listing.oppervlakte_advertentie == 97
    assert not scan.waarschuwingen


def test_scan_email_body_herkent_afwijkende_advertentie_oppervlakte():
    scan = scan_email_body(_kaart(oppervlakte="142", kamers="6"))
    assert scan.listings[0].oppervlakte_advertentie == 142


def test_scan_email_body_zonder_oppervlakte_geeft_none():
    body = """
    <a target="_blank" href="https://links.funda.nl/s/c/token1/hash1/22" rel="noopener">
      <span style="color:#0071b3;">Hillevliet 47 A</span>
    </a>
    <span>3073 KJ Rotterdam</span>
    <span>€ 260.000 k.k.</span>
    """
    scan = scan_email_body(body)
    assert scan.listings[0].oppervlakte_advertentie is None


def test_scan_email_body_zonder_toevoeging():
    scan = scan_email_body(_kaart(adres="Vredehagen 44", postcode="3078 CN", prijs="635.000"))
    listing = scan.listings[0]
    assert listing.huisnummer == "44"
    assert listing.toevoeging == ""
    assert listing.object_id == "3078CN-44"


def test_scan_email_body_herkent_letter_plus_cijfers_toevoeging():
    # Veelvoorkomend format bij Rotterdamse appartementen (bv. "91 A03") - zonder
    # koppelteken, in tegenstelling tot de simpele "47 A"-vorm hierboven.
    scan = scan_email_body(
        _kaart(adres="Rochussenstraat 197 B02", postcode="3024 EE", prijs="599.000")
    )
    assert not scan.waarschuwingen
    listing = scan.listings[0]
    assert listing.straatnaam == "Rochussenstraat"
    assert listing.huisnummer == "197"
    assert listing.toevoeging == "B02"
    assert listing.object_id == "3024EE-197B02"


def test_scan_email_body_meerdere_woningen_venster_loopt_niet_over():
    body = _kaart(
        url="https://links.funda.nl/s/c/token1/hash1/22",
        adres="Hillevliet 47 A",
        postcode="3073 KJ",
        prijs="260.000",
    ) + _kaart(
        url="https://links.funda.nl/s/c/token2/hash2/22",
        adres="Groene Hilledijk 378 B",
        postcode="3075 ED",
        prijs="400.000",
    )
    scan = scan_email_body(body)
    by_id = {listing.object_id: listing for listing in scan.listings}
    assert by_id["3073KJ-47A"].prijs == 260000
    assert by_id["3075ED-378B"].prijs == 400000


def test_scan_email_body_dedupliceert_op_object_id():
    body = _kaart() + _kaart()
    scan = scan_email_body(body)
    assert len(scan.listings) == 1


def test_scan_email_body_negeert_links_zonder_adres_achtige_tekst():
    body = '<a target="_blank" href="https://links.funda.nl/s/vb/token/hash/22"><span>hier</span></a>'
    scan = scan_email_body(body)
    assert scan.listings == []


def test_scan_email_body_lege_body():
    scan = scan_email_body("")
    assert scan.listings == []
    assert scan.waarschuwingen == []


def test_scan_email_body_geen_bekijk_alle_waarschuwing_meer():
    # De "Bekijk alle N woningen"-truncatiewaarschuwing is bewust weggehaald: de
    # NVM-mails zijn nu de hoofdbron met het volledige aanbod, dus dit is geen gemis.
    body = _kaart() + "Bekijk alle 3 woningen"
    scan = scan_email_body(body)
    assert len(scan.listings) == 1
    assert scan.waarschuwingen == []


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
        b"1": ("OK", [(b"1 (...)", b"Subject: Verwijder 3073KJ-47A\r\n\r\n")]),
        b"2": ("OK", [(b"2 (...)", b"Subject: Verwijder 3078CN-44 - iets\r\n\r\n")]),
    }
    imap = _mock_imap([b"1 2"], fetch_results)

    with patch("rotterdam_scanner.funda_mail.imaplib.IMAP4_SSL", return_value=imap):
        object_ids = fetch_verwijder_commandos(_config())

    assert object_ids == {"3073KJ-47A", "3078CN-44"}


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

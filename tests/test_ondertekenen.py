"""Unit-tests voor webapp/ondertekenen.py: het berekenen van het
betaalverzoek, het opzetten/bijhouden van een ondertekenronde, en het
opbouwen van het handtekeningenblok."""
import base64
from datetime import date
from decimal import Decimal

from kamerverhuur_scanner.models import Pand, Verhuurder
from webapp import ondertekenen


def _pand(**overrides) -> Pand:
    basis = dict(
        slug="mahoniestraat", naam="Mahoniestraat 15", google_sheet_id="x",
        google_sheet_worksheet="Huurders", history_worksheet="Historie",
        google_drive_folder_id=None, bunq_rekening_iban="NL81BUNQ2163127125",
        verhuurders=[
            Verhuurder(naam="Jurian Reckman", adres="Batavierenplantsoen 33, Haarlem"),
            Verhuurder(naam="Justin Winkelman", adres="Rijksstraatweg 98, Haarlem"),
        ],
    )
    basis.update(overrides)
    return Pand(**basis)


def _metadata(**overrides) -> dict:
    basis = dict(
        email="bence@example.com", huurder_naam="Bence Neumayer", kamer="1", borg="1000,00",
        huurprijs="919,00", ingangsdatum_iso="2026-07-10", borgsteller_naam="", borgsteller_email="",
    )
    basis.update(overrides)
    return basis


# --- bereken_betaalverzoek_bedrag ---


def test_bereken_betaalverzoek_bedrag_pro_rata_plus_borg():
    # juli heeft 31 dagen, ingangsdatum 10 juli -> 22 dagen resterend (10 t/m 31)
    totaal = ondertekenen.bereken_betaalverzoek_bedrag(
        huurprijs=Decimal("930.00"), borg=Decimal("1000.00"), ingangsdatum=date(2026, 7, 10)
    )
    verwachte_pro_rata = (Decimal("930.00") * 22 / 31).quantize(Decimal("0.01"))
    assert totaal == Decimal("1000.00") + verwachte_pro_rata


def test_bereken_betaalverzoek_bedrag_ingangsdatum_op_de_eerste_telt_hele_maand():
    totaal = ondertekenen.bereken_betaalverzoek_bedrag(
        huurprijs=Decimal("900.00"), borg=Decimal("0"), ingangsdatum=date(2026, 2, 1)
    )
    assert totaal == Decimal("900.00")  # februari 2026 heeft 28 dagen, volledige maand


def test_bereken_betaalverzoek_bedrag_ingangsdatum_op_laatste_dag_telt_1_dag():
    totaal = ondertekenen.bereken_betaalverzoek_bedrag(
        huurprijs=Decimal("930.00"), borg=Decimal("500.00"), ingangsdatum=date(2026, 7, 31)
    )
    verwachte_pro_rata = (Decimal("930.00") * 1 / 31).quantize(Decimal("0.01"))
    assert totaal == Decimal("500.00") + verwachte_pro_rata


# --- start_ondertekenronde ---


def test_start_ondertekenronde_bevat_huurder_en_alle_verhuurders(tmp_path):
    ronde = ondertekenen.start_ondertekenronde(
        _pand(), "mahoniestraat", "contract.html", _metadata(),
        verhuurder_emails=["jurian@example.com", "justin@example.com"], state_dir=str(tmp_path),
    )
    rollen = [(o["rol"], o["naam"], o["email"]) for o in ronde["ondertekenaars"]]
    assert ("huurder", "Bence Neumayer", "bence@example.com") in rollen
    assert ("verhuurder", "Jurian Reckman", "jurian@example.com") in rollen
    assert ("verhuurder", "Justin Winkelman", "justin@example.com") in rollen
    assert len(ronde["ondertekenaars"]) == 3  # geen borgsteller in deze metadata
    # elke ondertekenaar heeft een unieke token
    tokens = [o["token"] for o in ronde["ondertekenaars"]]
    assert len(set(tokens)) == len(tokens)


def test_start_ondertekenronde_voegt_borgsteller_toe_indien_bekend(tmp_path):
    metadata = _metadata(borgsteller_naam="Tamás Neumayer", borgsteller_email="tamas@example.com")
    ronde = ondertekenen.start_ondertekenronde(
        _pand(), "mahoniestraat", "contract.html", metadata,
        verhuurder_emails=["jurian@example.com", "justin@example.com"], state_dir=str(tmp_path),
    )
    borgsteller = next(o for o in ronde["ondertekenaars"] if o["rol"] == "borgsteller")
    assert borgsteller["naam"] == "Tamás Neumayer"
    assert borgsteller["email"] == "tamas@example.com"


def test_start_ondertekenronde_is_idempotent(tmp_path):
    eerste = ondertekenen.start_ondertekenronde(
        _pand(), "mahoniestraat", "contract.html", _metadata(),
        verhuurder_emails=["jurian@example.com", "justin@example.com"], state_dir=str(tmp_path),
    )
    tweede = ondertekenen.start_ondertekenronde(
        _pand(), "mahoniestraat", "contract.html", _metadata(),
        verhuurder_emails=["jurian@example.com", "justin@example.com"], state_dir=str(tmp_path),
    )
    # dezelfde tokens, geen nieuwe ronde/tokens aangemaakt bij een 2e aanroep
    assert eerste["ondertekenaars"] == tweede["ondertekenaars"]


def test_zoek_via_token_vindt_de_juiste_ondertekenaar(tmp_path):
    ronde = ondertekenen.start_ondertekenronde(
        _pand(), "mahoniestraat", "contract.html", _metadata(),
        verhuurder_emails=["jurian@example.com", "justin@example.com"], state_dir=str(tmp_path),
    )
    token = ronde["ondertekenaars"][0]["token"]
    gevonden = ondertekenen.zoek_via_token(token, str(tmp_path))
    assert gevonden is not None
    pand_slug, bestandsnaam, ondertekenaar = gevonden
    assert pand_slug == "mahoniestraat"
    assert bestandsnaam == "contract.html"
    assert ondertekenaar["token"] == token


def test_zoek_via_token_onbekende_token_geeft_none(tmp_path):
    assert ondertekenen.zoek_via_token("onbekend-token", str(tmp_path)) is None


# --- markeer_ondertekend / alles_getekend ---


def test_markeer_ondertekend_zet_tijdstip_ip_en_naam(tmp_path):
    ronde = ondertekenen.start_ondertekenronde(
        _pand(), "mahoniestraat", "contract.html", _metadata(),
        verhuurder_emails=["jurian@example.com", "justin@example.com"], state_dir=str(tmp_path),
    )
    huurder_id = ronde["ondertekenaars"][0]["id"]
    bijgewerkt = ondertekenen.markeer_ondertekend(
        "mahoniestraat", "contract.html", huurder_id, str(tmp_path),
        ip_adres="203.0.113.5", user_agent="Testbrowser/1.0", getekende_naam="Bence Neumayer",
    )
    huurder = next(o for o in bijgewerkt["ondertekenaars"] if o["id"] == huurder_id)
    assert huurder["ondertekend_op"] is not None
    assert huurder["ip_adres"] == "203.0.113.5"
    assert huurder["user_agent"] == "Testbrowser/1.0"
    assert huurder["getekende_naam"] == "Bence Neumayer"
    assert ondertekenen.alles_getekend(bijgewerkt) is False  # verhuurders hebben nog niet getekend


def test_markeer_ondertekend_is_idempotent_overschrijft_niet(tmp_path):
    ronde = ondertekenen.start_ondertekenronde(
        _pand(), "mahoniestraat", "contract.html", _metadata(),
        verhuurder_emails=["jurian@example.com", "justin@example.com"], state_dir=str(tmp_path),
    )
    huurder_id = ronde["ondertekenaars"][0]["id"]
    eerste = ondertekenen.markeer_ondertekend(
        "mahoniestraat", "contract.html", huurder_id, str(tmp_path), "1.1.1.1", "UA-1", "Eerste Naam"
    )
    tweede = ondertekenen.markeer_ondertekend(
        "mahoniestraat", "contract.html", huurder_id, str(tmp_path), "2.2.2.2", "UA-2", "Tweede Naam"
    )
    huurder = next(o for o in tweede["ondertekenaars"] if o["id"] == huurder_id)
    eerste_huurder = next(o for o in eerste["ondertekenaars"] if o["id"] == huurder_id)
    assert huurder["ip_adres"] == "1.1.1.1"
    assert huurder["ondertekend_op"] == eerste_huurder["ondertekend_op"]


def test_alles_getekend_true_als_iedereen_getekend_heeft(tmp_path):
    ronde = ondertekenen.start_ondertekenronde(
        _pand(), "mahoniestraat", "contract.html", _metadata(),
        verhuurder_emails=["jurian@example.com", "justin@example.com"], state_dir=str(tmp_path),
    )
    for o in ronde["ondertekenaars"]:
        ronde = ondertekenen.markeer_ondertekend(
            "mahoniestraat", "contract.html", o["id"], str(tmp_path), "1.1.1.1", "UA", o["naam"]
        )
    assert ondertekenen.alles_getekend(ronde) is True


# --- handtekening_base64_uit_data_url ---

_GELDIGE_PNG_DATA_URL = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_handtekening_base64_uit_data_url_geldig():
    payload = ondertekenen.handtekening_base64_uit_data_url(_GELDIGE_PNG_DATA_URL)
    assert payload is not None
    assert payload in _GELDIGE_PNG_DATA_URL


def test_handtekening_base64_uit_data_url_leeg_geeft_none():
    assert ondertekenen.handtekening_base64_uit_data_url("") is None
    assert ondertekenen.handtekening_base64_uit_data_url(None) is None


def test_handtekening_base64_uit_data_url_verkeerd_prefix_geeft_none():
    assert ondertekenen.handtekening_base64_uit_data_url("data:text/plain;base64,aGFsbG8=") is None
    assert ondertekenen.handtekening_base64_uit_data_url("niet-een-data-url") is None


def test_handtekening_base64_uit_data_url_ongeldige_base64_geeft_none():
    assert ondertekenen.handtekening_base64_uit_data_url("data:image/png;base64,!!!niet-valide!!!") is None


def test_handtekening_base64_uit_data_url_te_groot_geeft_none():
    groot_payload = base64.b64encode(b"x" * (ondertekenen._MAX_HANDTEKENING_BYTES + 1)).decode()
    assert ondertekenen.handtekening_base64_uit_data_url("data:image/png;base64," + groot_payload) is None


# --- bouw_handtekeningen_html ---


def test_bouw_handtekeningen_html_escaped_getypte_naam(tmp_path):
    ronde = ondertekenen.start_ondertekenronde(
        _pand(), "mahoniestraat", "contract.html", _metadata(),
        verhuurder_emails=["jurian@example.com", "justin@example.com"], state_dir=str(tmp_path),
    )
    huurder_id = ronde["ondertekenaars"][0]["id"]
    ronde = ondertekenen.markeer_ondertekend(
        "mahoniestraat", "contract.html", huurder_id, str(tmp_path),
        "203.0.113.5", "UA", '<script>alert(1)</script>',
    )
    html = ondertekenen.bouw_handtekeningen_html(ronde)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "203.0.113.5" in html


def test_bouw_handtekeningen_html_toont_getekende_afbeelding(tmp_path):
    ronde = ondertekenen.start_ondertekenronde(
        _pand(), "mahoniestraat", "contract.html", _metadata(),
        verhuurder_emails=["jurian@example.com", "justin@example.com"], state_dir=str(tmp_path),
    )
    huurder_id = ronde["ondertekenaars"][0]["id"]
    payload = ondertekenen.handtekening_base64_uit_data_url(_GELDIGE_PNG_DATA_URL)
    ronde = ondertekenen.markeer_ondertekend(
        "mahoniestraat", "contract.html", huurder_id, str(tmp_path),
        "203.0.113.5", "UA", "Bence Neumayer", payload,
    )
    html = ondertekenen.bouw_handtekeningen_html(ronde)
    assert f'src="data:image/png;base64,{payload}"' in html


def test_bouw_handtekeningen_html_zonder_afbeelding_toont_geen_img_tag(tmp_path):
    ronde = ondertekenen.start_ondertekenronde(
        _pand(), "mahoniestraat", "contract.html", _metadata(),
        verhuurder_emails=["jurian@example.com", "justin@example.com"], state_dir=str(tmp_path),
    )
    huurder_id = ronde["ondertekenaars"][0]["id"]
    ronde = ondertekenen.markeer_ondertekend(
        "mahoniestraat", "contract.html", huurder_id, str(tmp_path), "203.0.113.5", "UA", "Bence Neumayer",
    )
    html = ondertekenen.bouw_handtekeningen_html(ronde)
    assert "<img" not in html


# --- markeer_verzonden ---


def test_markeer_verzonden_zet_tijdstip(tmp_path):
    ondertekenen.start_ondertekenronde(
        _pand(), "mahoniestraat", "contract.html", _metadata(),
        verhuurder_emails=["jurian@example.com", "justin@example.com"], state_dir=str(tmp_path),
    )
    assert ondertekenen.lees_ondertekenronde("mahoniestraat", "contract.html", str(tmp_path))["verzonden_op"] is None
    ronde = ondertekenen.markeer_verzonden("mahoniestraat", "contract.html", str(tmp_path))
    assert ronde["verzonden_op"] is not None
    assert ondertekenen.lees_ondertekenronde(
        "mahoniestraat", "contract.html", str(tmp_path)
    )["verzonden_op"] == ronde["verzonden_op"]

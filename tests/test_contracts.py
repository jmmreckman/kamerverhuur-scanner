"""Tests voor het genereren van een huurcontract (HTML + PDF) op basis van het
sjabloon in contract_templates/huurovereenkomst_voorbeeld.html."""
from werkzeug.datastructures import ImmutableMultiDict

from kamerverhuur_scanner.models import Pand, Verhuurder
from webapp import contracts


def _pand(**overrides) -> Pand:
    basis = dict(
        slug="mahoniestraat", naam="Mahoniestraat 15", google_sheet_id="x",
        google_sheet_worksheet="Huurders", history_worksheet="Historie",
        google_drive_folder_id=None, bunq_rekening_iban="NL81BUNQ2163127125",
        postcode="3077WD", plaats="Rotterdam",
        verhuurders=[
            Verhuurder(naam="Jurian Reckman", adres="Batavierenplantsoen 33, Haarlem"),
            Verhuurder(naam="Justin Winkelman", adres="Rijksstraatweg 98, Haarlem"),
        ],
        rekeninghouder_naam="JMM Reckman",
        gedeelde_ruimtes="toilet, keuken, twee badkamers, tuin, schuur, wasruimte",
        bijzondere_bepalingen="De 'bubble/jet'-functie van het bad is defect.\nGarage blijft afgesloten.",
        gemeente_meldpunt="www.rotterdam.nl/ongewenst-verhuurgedrag-melden",
    )
    basis.update(overrides)
    return Pand(**basis)


def _form(**overrides) -> ImmutableMultiDict:
    basis = dict(
        kamer="1", kamer_omschrijving="ground floor garden side with own kitchen",
        huurder_naam="Bence Neumayer", geboortedatum="2000-11-27", geboorteplaats="Tatabánya, Hungary",
        studentnummer="1124601", studierichting="Consultancy and Entrepreneurship",
        borgsteller_naam="Tamás Neumayer", borgsteller_relatie="Vader",
        kale_huurprijs="711,49", servicekosten="207,51", huurprijs="919,00", borg="1000,00",
        aantal_bewoners="6", ingangsdatum="2026-07-01", einddatum="2028-07-01",
        bijzonderheden="",
    )
    basis.update(overrides)
    return ImmutableMultiDict(basis)


def test_genereer_contract_schrijft_html_bestand(tmp_path, monkeypatch):
    monkeypatch.setattr(contracts, "BASIS_OUTPUT_DIR", tmp_path)
    bestandsnaam = contracts.genereer_contract("mahoniestraat", _pand(), _form())
    pad = tmp_path / "mahoniestraat" / bestandsnaam
    assert pad.is_file()
    html = pad.read_text()
    assert "Bence Neumayer" in html
    assert "Jurian Reckman" in html
    assert "Justin Winkelman" in html
    assert "919,00" in html
    assert "6 tenants" in html
    assert "Tatabánya, Hungary" in html
    assert "Tamás Neumayer" in html
    assert "3077WD" in html
    assert "Rotterdam" in html
    assert "27-11-2000" in html  # datum omgezet naar dd-mm-jjjj
    assert "01-07-2026" in html
    assert "01-07-2028" in html


def test_genereer_contract_zonder_borgsteller_laat_artikel_12_niet_van_toepassing_zijn(tmp_path, monkeypatch):
    monkeypatch.setattr(contracts, "BASIS_OUTPUT_DIR", tmp_path)
    bestandsnaam = contracts.genereer_contract(
        "mahoniestraat", _pand(), _form(borgsteller_naam="", borgsteller_relatie="")
    )
    html = (tmp_path / "mahoniestraat" / bestandsnaam).read_text()
    assert "Guarantor:" not in html
    assert "Not applicable" in html


def test_genereer_contract_zonder_pandgegevens_toont_invulplekken(tmp_path, monkeypatch):
    monkeypatch.setattr(contracts, "BASIS_OUTPUT_DIR", tmp_path)
    leeg_pand = Pand(
        slug="baumannlaan", naam="Baumannlaan 70b", google_sheet_id="y", google_sheet_worksheet="Huurders",
        history_worksheet="Historie", google_drive_folder_id=None, bunq_rekening_iban="NL00TEST0000000000",
    )
    bestandsnaam = contracts.genereer_contract("baumannlaan", leeg_pand, _form(kamer="2"))
    html = (tmp_path / "baumannlaan" / bestandsnaam).read_text()
    assert "[fill in" in html.lower() or "[address]" in html


def test_genereer_pdf_zet_html_om_naar_pdf_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(contracts, "BASIS_OUTPUT_DIR", tmp_path)
    bestandsnaam = contracts.genereer_contract("mahoniestraat", _pand(), _form())
    pdf_bytes = contracts.genereer_pdf("mahoniestraat", bestandsnaam)
    assert pdf_bytes.startswith(b"%PDF")


def test_genereer_pdf_onbekend_bestand_geeft_filenotfound(tmp_path, monkeypatch):
    monkeypatch.setattr(contracts, "BASIS_OUTPUT_DIR", tmp_path)
    try:
        contracts.genereer_pdf("mahoniestraat", "bestaat-niet.html")
        assert False, "had een FileNotFoundError moeten geven"
    except FileNotFoundError:
        pass


def test_genereer_contract_bewaart_metadata_voor_mailen(tmp_path, monkeypatch):
    monkeypatch.setattr(contracts, "BASIS_OUTPUT_DIR", tmp_path)
    bestandsnaam = contracts.genereer_contract(
        "mahoniestraat", _pand(), _form(email="bence@example.com")
    )
    metadata = contracts.lees_metadata("mahoniestraat", bestandsnaam)
    assert metadata["email"] == "bence@example.com"
    assert metadata["huurder_naam"] == "Bence Neumayer"
    assert metadata["kamer"] == "1"
    assert metadata["borg"] == "1000,00"


def test_lees_metadata_zonder_bestand_geeft_lege_dict(tmp_path, monkeypatch):
    monkeypatch.setattr(contracts, "BASIS_OUTPUT_DIR", tmp_path)
    assert contracts.lees_metadata("mahoniestraat", "bestaat-niet.html") == {}


def test_bouw_concept_email_bevat_kamer_dochub_en_bold():
    pand = _pand()
    metadata = {"huurder_naam": "Bence Neumayer", "kamer": "1", "borg": "1000,00"}
    opgesteld = contracts.bouw_concept_email(pand, metadata)
    assert "1" in opgesteld["onderwerp"]
    assert pand.naam in opgesteld["onderwerp"]
    assert "Bence Neumayer" in opgesteld["tekst"]
    assert "DocHub" in opgesteld["tekst"]
    assert "Bold" in opgesteld["tekst"]
    assert "1000,00" in opgesteld["tekst"]
    assert "Jurian Reckman" in opgesteld["tekst"]  # ondertekening (AFZENDER_NAAM)

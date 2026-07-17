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


def test_genereer_contract_schrijft_html_bestand(tmp_path):
    bestandsnaam = contracts.genereer_contract("mahoniestraat", _pand(), _form(), state_dir=str(tmp_path))
    pad = tmp_path / "gegenereerde_contracten" / "mahoniestraat" / bestandsnaam
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


def test_genereer_contract_zonder_borgsteller_laat_artikel_12_niet_van_toepassing_zijn(tmp_path):
    bestandsnaam = contracts.genereer_contract(
        "mahoniestraat", _pand(), _form(borgsteller_naam="", borgsteller_relatie=""), state_dir=str(tmp_path)
    )
    html = (tmp_path / "gegenereerde_contracten" / "mahoniestraat" / bestandsnaam).read_text()
    assert "Guarantor:" not in html
    assert "Not applicable" in html


def test_genereer_contract_zonder_pandgegevens_toont_invulplekken(tmp_path):
    leeg_pand = Pand(
        slug="baumannlaan", naam="Baumannlaan 70b", google_sheet_id="y", google_sheet_worksheet="Huurders",
        history_worksheet="Historie", google_drive_folder_id=None, bunq_rekening_iban="NL00TEST0000000000",
    )
    bestandsnaam = contracts.genereer_contract(
        "baumannlaan", leeg_pand, _form(kamer="2"), state_dir=str(tmp_path)
    )
    html = (tmp_path / "gegenereerde_contracten" / "baumannlaan" / bestandsnaam).read_text()
    assert "[fill in" in html.lower() or "[address]" in html


def test_genereer_pdf_zet_html_om_naar_pdf_bytes(tmp_path):
    bestandsnaam = contracts.genereer_contract("mahoniestraat", _pand(), _form(), state_dir=str(tmp_path))
    pdf_bytes = contracts.genereer_pdf("mahoniestraat", bestandsnaam, state_dir=str(tmp_path))
    assert pdf_bytes.startswith(b"%PDF")


def test_genereer_pdf_onbekend_bestand_geeft_filenotfound(tmp_path):
    try:
        contracts.genereer_pdf("mahoniestraat", "bestaat-niet.html", state_dir=str(tmp_path))
        assert False, "had een FileNotFoundError moeten geven"
    except FileNotFoundError:
        pass


def test_verwijder_contract_verwijdert_html_en_metadata(tmp_path):
    bestandsnaam = contracts.genereer_contract(
        "mahoniestraat", _pand(), _form(email="bence@example.com"), state_dir=str(tmp_path)
    )
    output_dir = tmp_path / "gegenereerde_contracten" / "mahoniestraat"
    assert (output_dir / bestandsnaam).is_file()
    assert (output_dir / f"{bestandsnaam}.meta.json").is_file()

    contracts.verwijder_contract("mahoniestraat", bestandsnaam, state_dir=str(tmp_path))

    assert not (output_dir / bestandsnaam).is_file()
    assert not (output_dir / f"{bestandsnaam}.meta.json").is_file()


def test_verwijder_contract_van_onbekend_bestand_doet_niets(tmp_path):
    contracts.verwijder_contract("mahoniestraat", "bestaat-niet.html", state_dir=str(tmp_path))  # geen crash


def test_genereer_contract_bewaart_metadata_voor_mailen(tmp_path):
    bestandsnaam = contracts.genereer_contract(
        "mahoniestraat", _pand(),
        _form(email="bence@example.com", borgsteller_email="tamas@example.com"), state_dir=str(tmp_path)
    )
    metadata = contracts.lees_metadata("mahoniestraat", bestandsnaam, state_dir=str(tmp_path))
    assert metadata["email"] == "bence@example.com"
    assert metadata["huurder_naam"] == "Bence Neumayer"
    assert metadata["kamer"] == "1"
    assert metadata["borg"] == "1000,00"
    assert metadata["huurprijs"] == "919,00"
    assert metadata["ingangsdatum_iso"] == "2026-07-01"
    assert metadata["borgsteller_naam"] == "Tamás Neumayer"
    assert metadata["borgsteller_email"] == "tamas@example.com"


def test_lees_metadata_zonder_bestand_geeft_lege_dict(tmp_path):
    assert contracts.lees_metadata("mahoniestraat", "bestaat-niet.html", state_dir=str(tmp_path)) == {}


# --- Elektronisch ondertekenen: definitieve, ondertekende contractversie ---


def test_is_getekend_contract_herkent_achtervoegsel():
    assert contracts.is_getekend_contract("2026-07-10_1-bence-neumayer-getekend.html") is True
    assert contracts.is_getekend_contract("2026-07-10_1-bence-neumayer.html") is False


def test_genereer_getekend_contract_vervangt_handtekeningenblok(tmp_path):
    bestandsnaam = contracts.genereer_contract("mahoniestraat", _pand(), _form(), state_dir=str(tmp_path))

    getekend_bestandsnaam = contracts.genereer_getekend_contract(
        "mahoniestraat", bestandsnaam, "<p>ECHTE HANDTEKENINGEN HIER</p>", state_dir=str(tmp_path)
    )

    assert getekend_bestandsnaam == bestandsnaam.replace(".html", "-getekend.html")
    assert contracts.is_getekend_contract(getekend_bestandsnaam)
    html = (tmp_path / "gegenereerde_contracten" / "mahoniestraat" / getekend_bestandsnaam).read_text()
    assert "ECHTE HANDTEKENINGEN HIER" in html
    assert "(landlord)" not in html  # het lege handtekeningenblok is vervangen
    # de rest van het contract blijft ongewijzigd staan
    assert "Bence Neumayer" in html
    assert "919,00" in html
    # het concept zelf blijft ook gewoon bestaan
    assert (tmp_path / "gegenereerde_contracten" / "mahoniestraat" / bestandsnaam).is_file()


def test_genereer_getekend_contract_kopieert_metadata_naar_getekende_versie(tmp_path):
    # zodat gegevens die na volledige ondertekening nog nodig zijn (bv. voor
    # de bevestigingsmail) beschikbaar blijven, ook als het concept later
    # wordt verwijderd - zie test_contract_bevestiging.py voor de route-test
    # van dat scenario.
    bestandsnaam = contracts.genereer_contract(
        "mahoniestraat", _pand(), _form(email="bence@example.com"), state_dir=str(tmp_path)
    )
    getekend_bestandsnaam = contracts.genereer_getekend_contract(
        "mahoniestraat", bestandsnaam, "<p>handtekeningen</p>", state_dir=str(tmp_path)
    )
    metadata = contracts.lees_metadata("mahoniestraat", getekend_bestandsnaam, state_dir=str(tmp_path))
    assert metadata["email"] == "bence@example.com"
    assert metadata["kamer"] == "1"


def test_origineel_bestandsnaam_is_de_inverse_van_getekend_bestandsnaam():
    origineel = "2026-07-10_1-bence-neumayer.html"
    getekend = "2026-07-10_1-bence-neumayer-getekend.html"
    assert contracts.origineel_bestandsnaam(getekend) == origineel


def test_origineel_bestandsnaam_op_al_niet_getekende_naam_geeft_ongewijzigd():
    assert contracts.origineel_bestandsnaam("2026-07-10_1-bence-neumayer.html") == "2026-07-10_1-bence-neumayer.html"


def test_kopieer_metadata_zonder_bronmetadata_doet_niets(tmp_path):
    contracts.kopieer_metadata("mahoniestraat", "bestaat-niet.html", "ook-niet.html", state_dir=str(tmp_path))
    assert contracts.lees_metadata("mahoniestraat", "ook-niet.html", state_dir=str(tmp_path)) == {}


def test_bouw_concept_email_bevat_kamer_en_bold():
    pand = _pand()
    metadata = {"huurder_naam": "Bence Neumayer", "kamer": "1", "borg": "1000,00"}
    opgesteld = contracts.bouw_concept_email(pand, metadata)
    assert "1" in opgesteld["onderwerp"]
    assert pand.naam in opgesteld["onderwerp"]
    assert "Bence Neumayer" in opgesteld["tekst"]
    assert "sign the agreement electronically" in opgesteld["tekst"]
    assert "Bold" in opgesteld["tekst"]


def test_bouw_concept_email_zonder_bold_slot_noemt_bold_niet():
    pand = _pand(heeft_bold_slot=False)
    metadata = {"huurder_naam": "Bence Neumayer", "kamer": "1", "borg": "1000,00"}
    opgesteld = contracts.bouw_concept_email(pand, metadata)
    assert "Bold" not in opgesteld["tekst"]
    assert "rental agreement takes effect from its start date" in opgesteld["tekst"]


# --- bouw_bevestigingsmail ---


def test_bouw_bevestigingsmail_bold_slot_bevat_de_meegegeven_link():
    pand = _pand(heeft_bold_slot=True)
    metadata = {"huurder_naam": "Bence Neumayer", "kamer": "1"}
    opgesteld = contracts.bouw_bevestigingsmail(pand, metadata, bold_link="https://bold.example/invite/abc123")
    assert "Bence Neumayer" in opgesteld["tekst"]
    assert "signed by all parties" in opgesteld["tekst"]
    assert "https://bold.example/invite/abc123" in opgesteld["tekst"]
    assert "keybox" not in opgesteld["tekst"].lower()
    assert "1" in opgesteld["onderwerp"]
    assert pand.naam in opgesteld["onderwerp"]


def test_bouw_bevestigingsmail_baumannlaan_noemt_sleutelbox_code():
    pand = _pand(slug="baumannlaan", naam="Burgemeester Baumannlaan 70b", heeft_bold_slot=False)
    metadata = {"huurder_naam": "Bence Neumayer", "kamer": "1"}
    opgesteld = contracts.bouw_bevestigingsmail(pand, metadata)
    assert "keybox" in opgesteld["tekst"].lower()
    assert "1590" in opgesteld["tekst"]
    assert "Bold" not in opgesteld["tekst"]


def test_bouw_bevestigingsmail_overig_pand_zonder_bold_slot_heeft_geen_toegangsinstructies():
    pand = _pand(slug="anderpand", heeft_bold_slot=False)
    metadata = {"huurder_naam": "Bence Neumayer", "kamer": "1"}
    opgesteld = contracts.bouw_bevestigingsmail(pand, metadata)
    assert "Bold" not in opgesteld["tekst"]
    assert "keybox" not in opgesteld["tekst"].lower()
    assert "1590" not in opgesteld["tekst"]
    assert "signed by all parties" in opgesteld["tekst"]
    assert "wish you a pleasant stay" in opgesteld["tekst"]


# --- Aanpasbaar contractsjabloon ---


def test_lees_sjabloon_zonder_aanpassing_geeft_standaardtekst(tmp_path):
    # gelijk aan de standaardtekst, op de interne ARTIKELEN:START/EINDE-
    # markeringen na (die worden bij het samenvoegen verwijderd)
    voor, artikelen, na = contracts._split_sjabloon(contracts.lees_standaard_sjabloon())
    assert contracts.lees_sjabloon(str(tmp_path)) == voor + artikelen + na
    assert contracts.heeft_aangepast_sjabloon(str(tmp_path)) is False


def test_lees_standaard_artikelen_bevat_geen_html_document_boilerplate(tmp_path):
    artikelen = contracts.lees_standaard_artikelen()
    assert "Article 1" in artikelen
    assert "<!doctype" not in artikelen.lower()
    assert "<style>" not in artikelen.lower()
    # het standaardsjabloon (volledig document) heeft dit stuk wél
    assert "Article 1" in contracts.lees_standaard_sjabloon()


def test_schrijf_en_lees_aangepaste_artikelen(tmp_path):
    contracts.schrijf_artikelen(str(tmp_path), "<p>Custom artikel {{ huurder_naam }}</p>")
    assert contracts.heeft_aangepast_sjabloon(str(tmp_path)) is True
    assert contracts.lees_artikelen(str(tmp_path)) == "<p>Custom artikel {{ huurder_naam }}</p>"
    # de standaardtekst zelf blijft ongewijzigd beschikbaar
    assert "Custom artikel" not in contracts.lees_standaard_artikelen()
    # de vaste opmaak eromheen (partijentabel, handtekeningenblok) blijft in het volledige sjabloon staan
    volledig = contracts.lees_sjabloon(str(tmp_path))
    assert "Custom artikel" in volledig
    assert "Signatures" in volledig


def test_schrijf_artikelen_met_ongeldige_syntax_geeft_sjabloonfout_en_slaat_niet_op(tmp_path):
    try:
        contracts.schrijf_artikelen(str(tmp_path), "<p>{% if kapot %}geen endif</p>")
        assert False, "had een SjabloonFout moeten geven"
    except contracts.SjabloonFout:
        pass
    assert contracts.heeft_aangepast_sjabloon(str(tmp_path)) is False


def test_verwijder_sjabloon_override_zet_terug_naar_standaard(tmp_path):
    contracts.schrijf_artikelen(str(tmp_path), "<p>Custom</p>")
    contracts.verwijder_sjabloon_override(str(tmp_path))
    assert contracts.heeft_aangepast_sjabloon(str(tmp_path)) is False
    assert contracts.lees_artikelen(str(tmp_path)) == contracts.lees_standaard_artikelen()


def test_verwijder_sjabloon_override_zonder_aanpassing_doet_niets(tmp_path):
    contracts.verwijder_sjabloon_override(str(tmp_path))  # geen crash zonder bestaand override-bestand
    assert contracts.heeft_aangepast_sjabloon(str(tmp_path)) is False


def test_lees_artikelen_negeert_verouderde_volledig_document_override(tmp_path):
    # override-bestanden van vóór de tekstverwerker-editor bevatten nog een heel
    # HTML-document (incl. <!doctype>) - die moeten genegeerd worden, anders
    # komt de vaste opmaak dubbel in het contract terecht.
    (tmp_path / "contract_sjabloon.html").write_text(contracts.lees_standaard_sjabloon())
    assert contracts.heeft_aangepast_sjabloon(str(tmp_path)) is True
    assert contracts.lees_artikelen(str(tmp_path)) == contracts.lees_standaard_artikelen()


def test_genereer_contract_gebruikt_aangepaste_artikelen(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    contracts.schrijf_artikelen(str(state_dir), "<p>Aangepast contract voor {{ huurder_naam }}, kamer {{ kamer }}</p>")

    bestandsnaam = contracts.genereer_contract("mahoniestraat", _pand(), _form(), state_dir=str(state_dir))

    html = (state_dir / "gegenereerde_contracten" / "mahoniestraat" / bestandsnaam).read_text()
    assert "Aangepast contract voor Bence Neumayer, kamer 1" in html
    # de vaste opmaak (partijen, handtekeningen) staat er nog steeds omheen
    assert "Jurian Reckman" in html
    assert "Signatures" in html

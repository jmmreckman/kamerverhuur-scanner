"""Unittests voor kamerverhuur_scanner/../webapp/documentverzoek.py (state +
mailtekst-opbouw), los van de Flask-routes."""
from kamerverhuur_scanner.models import Pand
from webapp import documentverzoek

PAND = Pand(
    slug="mahoniestraat", naam="Mahoniestraat 15", google_sheet_id="fake",
    google_sheet_worksheet="Huurders", history_worksheet="Historie",
    google_drive_folder_id=None, bunq_rekening_iban="NL81BUNQ2163127125",
)


def test_maak_sleutel_is_deterministisch():
    a = documentverzoek.maak_sleutel("1", "Jane Doe", "jane@example.com")
    b = documentverzoek.maak_sleutel("1", "Jane Doe", "jane@example.com")
    assert a == b
    assert a != documentverzoek.maak_sleutel("2", "Jane Doe", "jane@example.com")


def test_start_documentverzoek_is_idempotent(tmp_path):
    eerste = documentverzoek.start_documentverzoek(
        "mahoniestraat", "1", "Jane Doe", "jane@example.com", "+31612345678", str(tmp_path)
    )
    tweede = documentverzoek.start_documentverzoek(
        "mahoniestraat", "1", "Jane Doe", "jane@example.com", "+31612345678", str(tmp_path)
    )
    assert eerste["token"] == tweede["token"]
    assert eerste["sleutel"] == tweede["sleutel"]


def test_zoek_via_token_vindt_pand_en_verzoek(tmp_path):
    verzoek = documentverzoek.start_documentverzoek(
        "mahoniestraat", "1", "Jane Doe", "jane@example.com", "+31612345678", str(tmp_path)
    )
    gevonden = documentverzoek.zoek_via_token(verzoek["token"], str(tmp_path))
    assert gevonden is not None
    pand_slug, gevonden_verzoek = gevonden
    assert pand_slug == "mahoniestraat"
    assert gevonden_verzoek["sleutel"] == verzoek["sleutel"]


def test_zoek_via_token_onbekende_token_geeft_none(tmp_path):
    assert documentverzoek.zoek_via_token("onbekend", str(tmp_path)) is None


def test_markeer_verzonden_zet_tijdstip(tmp_path):
    verzoek = documentverzoek.start_documentverzoek(
        "mahoniestraat", "1", "Jane Doe", "jane@example.com", "+31612345678", str(tmp_path)
    )
    assert verzoek["verzonden_op"] is None
    bijgewerkt = documentverzoek.markeer_verzonden("mahoniestraat", verzoek["sleutel"], str(tmp_path))
    assert bijgewerkt["verzonden_op"] is not None


def test_voeg_documenten_toe_vult_lijst_aan(tmp_path):
    verzoek = documentverzoek.start_documentverzoek(
        "mahoniestraat", "1", "Jane Doe", "jane@example.com", "+31612345678", str(tmp_path)
    )
    documentverzoek.voeg_documenten_toe(
        "mahoniestraat", verzoek["sleutel"],
        [{"categorie": "ID", "bestand_id": "abc", "naam": "id.jpg", "mimetype": "image/jpeg"}],
        str(tmp_path),
    )
    bijgewerkt = documentverzoek.voeg_documenten_toe(
        "mahoniestraat", verzoek["sleutel"],
        [{"categorie": "Inkomen", "bestand_id": "def", "naam": "loon.pdf", "mimetype": "application/pdf"}],
        str(tmp_path),
    )
    assert len(bijgewerkt["documenten"]) == 2
    assert bijgewerkt["ontvangen_op"] is not None


def test_bouw_documentverzoek_mail_bevat_kamer_en_link():
    mail = documentverzoek.bouw_documentverzoek_mail(PAND, "1", "Jane Doe", "https://steenhub.nl/documenten/abc")
    assert "Jane Doe" in mail["tekst"]
    assert "https://steenhub.nl/documenten/abc" in mail["tekst"]
    assert "ID card or passport" in mail["tekst"]
    assert "room 1" in mail["onderwerp"]
    assert "Mahoniestraat 15" in mail["onderwerp"]

import json

from kamerverhuur_scanner.properties import load_properties, verwijder_pand, zet_pand


def test_zet_pand_voegt_nieuw_pand_toe(tmp_path):
    path = tmp_path / "properties.json"
    path.write_text("[]")
    zet_pand(str(path), "baumannlaan", {
        "naam": "Burgemeester Baumannlaan 70b", "google_sheet_id": "abc",
        "google_sheet_worksheet": "Huurders", "history_worksheet": "Historie",
        "aanmeldingen_worksheet": "Aanmeldingen", "google_drive_folder_id": None,
        "bunq_rekening_iban": "NL00TEST0000000000",
    })
    panden = load_properties(str(path))
    assert len(panden) == 1
    assert panden[0].slug == "baumannlaan"
    assert panden[0].naam == "Burgemeester Baumannlaan 70b"


def test_zet_pand_werkt_bestaand_pand_bij_op_basis_van_slug(tmp_path):
    path = tmp_path / "properties.json"
    path.write_text(json.dumps([
        {"slug": "mahoniestraat", "naam": "Mahoniestraat 15", "google_sheet_id": "x",
         "bunq_rekening_iban": "NL81BUNQ2163127125"},
    ]))
    zet_pand(str(path), "mahoniestraat", {
        "naam": "Mahoniestraat 15 (bijgewerkt)", "google_sheet_id": "x",
        "google_sheet_worksheet": "Huurders", "history_worksheet": "Historie",
        "aanmeldingen_worksheet": "Aanmeldingen", "google_drive_folder_id": None,
        "bunq_rekening_iban": "NL81BUNQ2163127125",
    })
    panden = load_properties(str(path))
    assert len(panden) == 1
    assert panden[0].naam == "Mahoniestraat 15 (bijgewerkt)"


def test_verwijder_pand(tmp_path):
    path = tmp_path / "properties.json"
    path.write_text(json.dumps([
        {"slug": "mahoniestraat", "naam": "Mahoniestraat 15", "google_sheet_id": "x",
         "bunq_rekening_iban": "NL81BUNQ2163127125"},
        {"slug": "baumannlaan", "naam": "Baumannlaan 70b", "google_sheet_id": "y",
         "bunq_rekening_iban": "NL00TEST0000000000"},
    ]))
    verwijder_pand(str(path), "baumannlaan")
    panden = load_properties(str(path))
    assert [p.slug for p in panden] == ["mahoniestraat"]

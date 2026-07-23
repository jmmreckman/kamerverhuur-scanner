import json
from decimal import Decimal

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


def test_extra_bcc_als_lijst_uit_zet_pand(tmp_path):
    path = tmp_path / "properties.json"
    path.write_text("[]")
    zet_pand(str(path), "mahoniestraat", {
        "naam": "Mahoniestraat 15", "google_sheet_id": "x",
        "bunq_rekening_iban": "NL81BUNQ2163127125", "extra_bcc": ["justin@example.com"],
    })
    panden = load_properties(str(path))
    assert panden[0].extra_bcc == ["justin@example.com"]


def test_onderhoud_reserve_wordt_geparsed_naar_decimal(tmp_path):
    path = tmp_path / "properties.json"
    path.write_text("[]")
    zet_pand(str(path), "mahoniestraat", {
        "naam": "Mahoniestraat 15", "google_sheet_id": "x",
        "bunq_rekening_iban": "NL81BUNQ2163127125", "onderhoud_reserve_per_maand": "€ 50,00",
    })
    panden = load_properties(str(path))
    assert panden[0].onderhoud_reserve_per_maand == Decimal("50.00")


def test_onderhoud_reserve_ontbreekt_geeft_none(tmp_path):
    path = tmp_path / "properties.json"
    path.write_text("[]")
    zet_pand(str(path), "mahoniestraat", {
        "naam": "Mahoniestraat 15", "google_sheet_id": "x", "bunq_rekening_iban": "NL81BUNQ2163127125",
    })
    panden = load_properties(str(path))
    assert panden[0].onderhoud_reserve_per_maand is None


def test_extra_bcc_ontbreekt_geeft_lege_lijst(tmp_path):
    path = tmp_path / "properties.json"
    path.write_text(json.dumps([
        {"slug": "baumannlaan", "naam": "Baumannlaan 70b", "google_sheet_id": "y",
         "bunq_rekening_iban": "NL00TEST0000000000"},
    ]))
    panden = load_properties(str(path))
    assert panden[0].extra_bcc == []


def test_extra_bcc_als_komma_string_wordt_genormaliseerd(tmp_path):
    path = tmp_path / "properties.json"
    path.write_text(json.dumps([
        {"slug": "mahoniestraat", "naam": "Mahoniestraat 15", "google_sheet_id": "x",
         "bunq_rekening_iban": "NL81BUNQ2163127125", "extra_bcc": "justin@example.com, extra@example.com"},
    ]))
    panden = load_properties(str(path))
    assert panden[0].extra_bcc == ["justin@example.com", "extra@example.com"]


def test_verhuurders_als_lijst_dicts_uit_zet_pand(tmp_path):
    path = tmp_path / "properties.json"
    path.write_text("[]")
    zet_pand(str(path), "mahoniestraat", {
        "naam": "Mahoniestraat 15", "google_sheet_id": "x",
        "bunq_rekening_iban": "NL81BUNQ2163127125",
        "verhuurders": [
            {"naam": "Jurian Reckman", "adres": "Batavierenplantsoen 33, Haarlem"},
            {"naam": "Justin Winkelman", "adres": "Rijksstraatweg 98, Haarlem"},
        ],
        "postcode": "3077WD", "plaats": "Rotterdam", "rekeninghouder_naam": "JMM Reckman",
        "gedeelde_ruimtes": "keuken, badkamer, tuin", "bijzondere_bepalingen": "Geen huisdieren.",
        "gemeente_meldpunt": "www.rotterdam.nl/ongewenst-verhuurgedrag-melden",
    })
    panden = load_properties(str(path))
    pand = panden[0]
    assert [v.naam for v in pand.verhuurders] == ["Jurian Reckman", "Justin Winkelman"]
    assert pand.verhuurders[0].adres == "Batavierenplantsoen 33, Haarlem"
    assert pand.postcode == "3077WD"
    assert pand.plaats == "Rotterdam"
    assert pand.rekeninghouder_naam == "JMM Reckman"
    assert pand.gedeelde_ruimtes == "keuken, badkamer, tuin"
    assert pand.bijzondere_bepalingen == "Geen huisdieren."
    assert pand.gemeente_meldpunt == "www.rotterdam.nl/ongewenst-verhuurgedrag-melden"


def test_verhuurders_als_tekst_met_pipe_wordt_genormaliseerd(tmp_path):
    path = tmp_path / "properties.json"
    path.write_text(json.dumps([
        {"slug": "mahoniestraat", "naam": "Mahoniestraat 15", "google_sheet_id": "x",
         "bunq_rekening_iban": "NL81BUNQ2163127125",
         "verhuurders": "Jurian Reckman | Batavierenplantsoen 33, Haarlem\nJustin Winkelman"},
    ]))
    panden = load_properties(str(path))
    verhuurders = panden[0].verhuurders
    assert verhuurders[0].naam == "Jurian Reckman"
    assert verhuurders[0].adres == "Batavierenplantsoen 33, Haarlem"
    assert verhuurders[1].naam == "Justin Winkelman"
    assert verhuurders[1].adres == ""


def test_verhuurders_ontbreekt_geeft_lege_lijst(tmp_path):
    path = tmp_path / "properties.json"
    path.write_text(json.dumps([
        {"slug": "baumannlaan", "naam": "Baumannlaan 70b", "google_sheet_id": "y",
         "bunq_rekening_iban": "NL00TEST0000000000"},
    ]))
    panden = load_properties(str(path))
    assert panden[0].verhuurders == []


def test_sleutels_als_lijst_strings_uit_zet_pand(tmp_path):
    path = tmp_path / "properties.json"
    path.write_text("[]")
    zet_pand(str(path), "mahoniestraat", {
        "naam": "Mahoniestraat 15", "google_sheet_id": "x",
        "bunq_rekening_iban": "NL81BUNQ2163127125",
        "sleutels": ["Lips 961 zolder straatkant", "Nemef 1240 BG straatkant"],
    })
    panden = load_properties(str(path))
    assert panden[0].sleutels == ["Lips 961 zolder straatkant", "Nemef 1240 BG straatkant"]


def test_sleutels_als_tekst_per_regel_wordt_genormaliseerd(tmp_path):
    path = tmp_path / "properties.json"
    path.write_text(json.dumps([
        {"slug": "mahoniestraat", "naam": "Mahoniestraat 15", "google_sheet_id": "x",
         "bunq_rekening_iban": "NL81BUNQ2163127125",
         "sleutels": "Lips 961 zolder straatkant\n\nNemef 1240 BG straatkant\n"},
    ]))
    panden = load_properties(str(path))
    assert panden[0].sleutels == ["Lips 961 zolder straatkant", "Nemef 1240 BG straatkant"]


def test_sleutels_ontbreekt_geeft_lege_lijst(tmp_path):
    path = tmp_path / "properties.json"
    path.write_text(json.dumps([
        {"slug": "baumannlaan", "naam": "Baumannlaan 70b", "google_sheet_id": "y",
         "bunq_rekening_iban": "NL00TEST0000000000"},
    ]))
    panden = load_properties(str(path))
    assert panden[0].sleutels == []
    assert panden[0].postcode == ""
    assert panden[0].plaats == ""


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

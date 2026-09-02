"""Tests voor lokale opslag van aanbod-foto's/video's en bewijsstukken -
vervangt Google Drive-uploads (die altijd mislukken voor een service account
zonder eigen opslagquotum, zie kamerverhuur_scanner/lokale_media.py)."""
from decimal import Decimal

from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.lokale_media import LokaleMediaClient
from kamerverhuur_scanner.models import Pand


def _config(tmp_path) -> Config:
    return Config(
        google_service_account_file="fake.json", properties_file="properties.json",
        bunq_conf_file="fake.conf", bunq_environment="PRODUCTION", bunq_api_key=None,
        users_file="users.json", flask_secret_key="test-secret",
        bedrag_tolerantie=Decimal("0.01"), vooruitbetaling_dagen=14, state_dir=str(tmp_path),
    )


def _pand() -> Pand:
    return Pand(
        slug="mahoniestraat", naam="Mahoniestraat 15", google_sheet_id="x",
        google_sheet_worksheet="Huurders", history_worksheet="Historie",
        bunq_rekening_iban="NL91ABNA0417164300",
    )


def test_lege_kamer_heeft_geen_bestanden(tmp_path):
    client = LokaleMediaClient(_config(tmp_path), _pand(), "aanbod")
    assert client.list_bestanden("BG straatkant") == []


def test_upload_en_terugvinden(tmp_path):
    client = LokaleMediaClient(_config(tmp_path), _pand(), "aanbod")
    bestand_id = client.upload_bestand("BG straatkant", "foto.jpg", "image/jpeg", b"fake-jpeg-bytes")

    bestanden = client.list_bestanden("BG straatkant")
    assert len(bestanden) == 1
    assert bestanden[0].id == bestand_id
    assert bestanden[0].naam == "foto.jpg"
    assert bestanden[0].mimetype == "image/jpeg"
    assert bestanden[0].grootte == len(b"fake-jpeg-bytes")

    gevonden = client.lees_bestand("BG straatkant", bestand_id)
    assert gevonden == ("foto.jpg", "image/jpeg", b"fake-jpeg-bytes")


def test_verwijderen(tmp_path):
    client = LokaleMediaClient(_config(tmp_path), _pand(), "aanbod")
    bestand_id = client.upload_bestand("1", "foto.jpg", "image/jpeg", b"data")
    client.verwijder_bestand("1", bestand_id)
    assert client.list_bestanden("1") == []
    assert client.lees_bestand("1", bestand_id) is None


def test_kamers_blijven_gescheiden(tmp_path):
    client = LokaleMediaClient(_config(tmp_path), _pand(), "aanbod")
    client.upload_bestand("1", "kamer1.jpg", "image/jpeg", b"data1")
    client.upload_bestand("2", "kamer2.jpg", "image/jpeg", b"data2")
    assert len(client.list_bestanden("1")) == 1
    assert len(client.list_bestanden("2")) == 1
    assert client.list_bestanden("1")[0].naam == "kamer1.jpg"


def test_categorieen_blijven_gescheiden(tmp_path):
    config = _config(tmp_path)
    aanbod = LokaleMediaClient(config, _pand(), "aanbod")
    aanmeldingen = LokaleMediaClient(config, _pand(), "aanmeldingen")
    aanbod.upload_bestand("1", "foto.jpg", "image/jpeg", b"foto")
    assert aanbod.list_bestanden("1") != []
    assert aanmeldingen.list_bestanden("1") == []


def test_lees_bestand_onbekend_id_geeft_none(tmp_path):
    client = LokaleMediaClient(_config(tmp_path), _pand(), "aanbod")
    assert client.lees_bestand("1", "bestaat-niet.jpg") is None


def test_verwijder_bestand_dat_van_een_andere_kamer_is_werkt_niet(tmp_path):
    # Path-traversal-achtige aanroep (../<andere kamer>/<bestand>) mag geen
    # bestand buiten de eigen kamermap raken.
    client = LokaleMediaClient(_config(tmp_path), _pand(), "aanbod")
    bestand_id = client.upload_bestand("1", "foto.jpg", "image/jpeg", b"data")
    client.verwijder_bestand("2", f"../1/{bestand_id}")
    assert client.lees_bestand("1", bestand_id) is not None

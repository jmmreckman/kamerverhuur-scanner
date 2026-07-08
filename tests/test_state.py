"""Tests voor de 'laatste controle'-cache - moet in een instelbare map
opgeslagen worden (STATE_DIR), anders is de cache na elke herbuild van de
Docker-container weer leeg (niet-volume paden worden dan gewist)."""
from decimal import Decimal

from kamerverhuur_scanner import state
from kamerverhuur_scanner.models import Status, Tenant, TenantResult


def _result() -> TenantResult:
    tenant = Tenant(row_index=2, naam="Jan", kamer="1", verwacht_bedrag=Decimal("650.00"))
    return TenantResult(tenant=tenant, ontvangen_bedrag=Decimal("650.00"), status=Status.BETAALD)


def test_save_en_load_gebruiken_state_dir(tmp_path):
    state.save("mahoniestraat", [_result()], 0, state_dir=str(tmp_path))

    bestanden = list(tmp_path.iterdir())
    assert len(bestanden) == 1
    assert bestanden[0].name == "laatste_resultaat_mahoniestraat.json"

    geladen = state.load("mahoniestraat", state_dir=str(tmp_path))
    assert geladen is not None
    assert geladen["resultaten"][0]["kamer"] == "1"


def test_load_in_andere_state_dir_vindt_niets(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    state.save("mahoniestraat", [_result()], 0, state_dir=str(tmp_path / "a"))
    assert state.load("mahoniestraat", state_dir=str(tmp_path / "b")) is None


def test_email_verzonden_op_zonder_markering_geeft_none(tmp_path):
    assert state.email_verzonden_op("mahoniestraat", "3", "herinnering", "2026-07", state_dir=str(tmp_path)) is None


def test_markeer_email_verzonden_en_opvragen(tmp_path):
    state.markeer_email_verzonden("mahoniestraat", "3", "herinnering", "2026-07", state_dir=str(tmp_path))

    verzonden_op = state.email_verzonden_op("mahoniestraat", "3", "herinnering", "2026-07", state_dir=str(tmp_path))
    assert verzonden_op is not None


def test_markeer_email_verzonden_onderscheidt_soort_en_kamer(tmp_path):
    state.markeer_email_verzonden("mahoniestraat", "3", "herinnering", "2026-07", state_dir=str(tmp_path))

    # andere soort, andere kamer: geen van beide gemarkeerd
    assert state.email_verzonden_op("mahoniestraat", "3", "ingebrekestelling", "2026-07", state_dir=str(tmp_path)) is None
    assert state.email_verzonden_op("mahoniestraat", "4", "herinnering", "2026-07", state_dir=str(tmp_path)) is None


def test_markeer_email_verzonden_reset_bij_nieuwe_maand(tmp_path):
    state.markeer_email_verzonden("mahoniestraat", "3", "herinnering", "2026-06", state_dir=str(tmp_path))
    # een nieuwe maand heeft nog geen eigen markering, ook al is dezelfde
    # kamer/soort al eens eerder (in een vorige maand) verzonden
    assert state.email_verzonden_op("mahoniestraat", "3", "herinnering", "2026-07", state_dir=str(tmp_path)) is None


def test_aanzegging_is_afgehandeld_zonder_markering_is_false(tmp_path):
    assert state.aanzegging_is_afgehandeld("mahoniestraat", "3", "2026-08-31", state_dir=str(tmp_path)) is False


def test_markeer_aanzegging_afgehandeld_en_opvragen(tmp_path):
    state.markeer_aanzegging_afgehandeld("mahoniestraat", "3", "2026-08-31", state_dir=str(tmp_path))
    assert state.aanzegging_is_afgehandeld("mahoniestraat", "3", "2026-08-31", state_dir=str(tmp_path)) is True


def test_markeer_aanzegging_afgehandeld_reset_bij_nieuwe_einddatum(tmp_path):
    state.markeer_aanzegging_afgehandeld("mahoniestraat", "3", "2026-08-31", state_dir=str(tmp_path))
    # een nieuw contract met een andere einddatum voor dezelfde kamer is een
    # nieuwe aanzegging - de oude markering geldt daar niet voor
    assert state.aanzegging_is_afgehandeld("mahoniestraat", "3", "2027-01-31", state_dir=str(tmp_path)) is False

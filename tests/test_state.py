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

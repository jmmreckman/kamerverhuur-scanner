"""Tests voor de betrouwbaarheidsscore en het aanvullen van de lopende
kalendermaand in de getoonde betaalgeschiedenis."""
from datetime import date
from decimal import Decimal

from kamerverhuur_scanner.models import HistorieRegel, Status
from webapp.reliability import bereken_betrouwbaarheid, voeg_actuele_maand_toe


def _regel(maand, status=Status.BETAALD):
    return HistorieRegel(
        maand=maand, kamer="1", huurder="Henri", verwacht_bedrag=Decimal("650.00"),
        ontvangen_bedrag=Decimal("650.00") if status == Status.BETAALD else Decimal("0"),
        status=status,
    )


def test_bereken_betrouwbaarheid_zonder_geschiedenis_geeft_none():
    assert bereken_betrouwbaarheid([]) is None


def test_bereken_betrouwbaarheid_percentage():
    geschiedenis = [_regel("2026-05"), _regel("2026-06", Status.NIET_ONTVANGEN)]
    resultaat = bereken_betrouwbaarheid(geschiedenis)
    assert resultaat == {"percentage": 50, "op_orde": 1, "totaal": 2}


def test_voeg_actuele_maand_toe_zonder_bestaande_regel_voegt_toe_uit_cache():
    geschiedenis = [_regel("2026-06", Status.NIET_ONTVANGEN)]
    cache_status = {"verwacht_bedrag": "650.00", "ontvangen_bedrag": "0", "status": "Nog niet ontvangen"}
    resultaat = voeg_actuele_maand_toe(
        geschiedenis, cache_status, "1", "Henri", vandaag=date(2026, 7, 8)
    )
    maanden = [r.maand for r in resultaat]
    assert maanden == ["2026-06", "2026-07"]
    assert resultaat[-1].status == Status.NIET_ONTVANGEN
    assert resultaat[-1].huurder == "Henri"


def test_voeg_actuele_maand_toe_als_al_aanwezig_verandert_niets():
    geschiedenis = [_regel("2026-06"), _regel("2026-07")]
    cache_status = {"verwacht_bedrag": "650.00", "ontvangen_bedrag": "0", "status": "Nog niet ontvangen"}
    resultaat = voeg_actuele_maand_toe(geschiedenis, cache_status, "1", "Henri", vandaag=date(2026, 7, 8))
    assert resultaat == geschiedenis


def test_voeg_actuele_maand_toe_zonder_cache_status_verandert_niets():
    geschiedenis = [_regel("2026-06")]
    resultaat = voeg_actuele_maand_toe(geschiedenis, None, "1", "Henri", vandaag=date(2026, 7, 8))
    assert resultaat == geschiedenis


def test_voeg_actuele_maand_toe_op_lege_geschiedenis():
    cache_status = {"verwacht_bedrag": "650.00", "ontvangen_bedrag": "650.00", "status": "Betaald"}
    resultaat = voeg_actuele_maand_toe([], cache_status, "1", "Henri", vandaag=date(2026, 7, 8))
    assert len(resultaat) == 1
    assert resultaat[0].maand == "2026-07"
    assert resultaat[0].status == Status.BETAALD

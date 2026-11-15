from rotterdam_scanner.verkoopstatus import (
    BESCHIKBAAR,
    IN_OPTIE,
    INGETROKKEN,
    ONBEKEND,
    ONDER_BOD,
    VERKOCHT,
    VERKOCHT_ONDER_VOORBEHOUD,
    categoriseer_verkoopstatus,
    is_beschikbaar,
    label_voor,
)


def test_enum_waarden():
    assert categoriseer_verkoopstatus("BESCHIKBAAR") == BESCHIKBAAR
    assert categoriseer_verkoopstatus("ONDER_BOD") == ONDER_BOD
    assert categoriseer_verkoopstatus("ONDER_OPTIE") == IN_OPTIE
    assert categoriseer_verkoopstatus("VERKOCHT") == VERKOCHT
    assert categoriseer_verkoopstatus("VERKOCHT_ONDER_VOORBEHOUD") == VERKOCHT_ONDER_VOORBEHOUD
    assert categoriseer_verkoopstatus("INGETROKKEN") == INGETROKKEN


def test_nl_labels():
    assert categoriseer_verkoopstatus("Beschikbaar") == BESCHIKBAAR
    assert categoriseer_verkoopstatus("Onder bod") == ONDER_BOD
    assert categoriseer_verkoopstatus("Verkocht onder voorbehoud") == VERKOCHT_ONDER_VOORBEHOUD
    assert categoriseer_verkoopstatus("Te koop") == BESCHIKBAAR


def test_voorbehoud_vóór_verkocht():
    # 'Verkocht onder voorbehoud' bevat ook 'verkocht' - mag niet als definitief verkocht tellen.
    assert categoriseer_verkoopstatus("Verkocht onder voorbehoud") == VERKOCHT_ONDER_VOORBEHOUD


def test_leeg_en_onbekend():
    assert categoriseer_verkoopstatus(None) == ONBEKEND
    assert categoriseer_verkoopstatus("") == ONBEKEND
    assert categoriseer_verkoopstatus("   ") == ONBEKEND
    assert categoriseer_verkoopstatus("IETS_NIEUWS") == ONBEKEND


def test_helpers():
    assert is_beschikbaar(BESCHIKBAAR) is True
    assert is_beschikbaar(ONDER_BOD) is False
    assert label_voor(ONDER_BOD) == "Onder bod"
    assert label_voor(None) == "Onbekend"

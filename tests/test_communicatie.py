import pytest

from webapp.communicatie import (
    CommunicatieFout,
    formatteer_geschiedenis_voor_ai,
    parse_chatgeschiedenis,
    serialiseer_chatgeschiedenis,
)


def test_parse_chatgeschiedenis_leeg_geeft_lege_lijst():
    assert parse_chatgeschiedenis("") == []


def test_serialiseer_en_parse_round_trip():
    chat = [{"role": "user", "content": "hoi"}, {"role": "assistant", "content": "hallo"}]
    ruw = serialiseer_chatgeschiedenis(chat)
    assert parse_chatgeschiedenis(ruw) == chat


def test_parse_chatgeschiedenis_ongeldige_json_geeft_fout():
    with pytest.raises(CommunicatieFout):
        parse_chatgeschiedenis("dit is geen json")


def test_parse_chatgeschiedenis_verkeerde_structuur_geeft_fout():
    with pytest.raises(CommunicatieFout):
        parse_chatgeschiedenis('[{"role": "systeem", "content": "hoi"}]')
    with pytest.raises(CommunicatieFout):
        parse_chatgeschiedenis('[{"role": "user"}]')
    with pytest.raises(CommunicatieFout):
        parse_chatgeschiedenis('"gewoon een string"')


def test_formatteer_geschiedenis_voor_ai():
    rijen = [
        ["10-07-2026 12:00", "1", "Jane Doe", "Inkomend", "Verwarming kapot", "De verwarming doet het niet."],
        ["11-07-2026 09:00", "1", "Jane Doe", "Uitgaand", "", "We sturen een monteur langs."],
    ]
    tekst = formatteer_geschiedenis_voor_ai(rijen)
    assert "[10-07-2026 12:00] Inkomend - Verwarming kapot" in tekst
    assert "De verwarming doet het niet." in tekst
    assert "[11-07-2026 09:00] Uitgaand\nWe sturen een monteur langs." in tekst


def test_formatteer_geschiedenis_voor_ai_beperkt_tot_recentste_20():
    rijen = [[f"dag-{i}", "1", "Jane", "Inkomend", "", f"bericht {i}"] for i in range(30)]
    tekst = formatteer_geschiedenis_voor_ai(rijen)
    assert "bericht 0" not in tekst
    assert "bericht 29" in tekst
    assert "bericht 10" in tekst

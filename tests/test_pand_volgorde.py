"""Tests voor het bewaren/laden/sorteren van de zelfgekozen pand-volgorde
(versleepbare tegels op de pandkiezer)."""
from dataclasses import dataclass

from kamerverhuur_scanner import state


@dataclass
class _P:
    slug: str


def test_bewaar_en_laad_volgorde_roundtrip(tmp_path):
    state.bewaar_pand_volgorde("jurian", ["baumannlaan", "mahoniestraat", "dordtselaan"], str(tmp_path))
    assert state.laad_pand_volgorde("jurian", str(tmp_path)) == ["baumannlaan", "mahoniestraat", "dordtselaan"]


def test_volgorde_is_per_gebruiker(tmp_path):
    state.bewaar_pand_volgorde("jurian", ["a", "b"], str(tmp_path))
    state.bewaar_pand_volgorde("justin", ["b", "a"], str(tmp_path))
    assert state.laad_pand_volgorde("jurian", str(tmp_path)) == ["a", "b"]
    assert state.laad_pand_volgorde("justin", str(tmp_path)) == ["b", "a"]


def test_geen_volgorde_geeft_lege_lijst(tmp_path):
    assert state.laad_pand_volgorde("iemand", str(tmp_path)) == []


def test_sorteer_op_opgeslagen_volgorde():
    panden = [_P("mahoniestraat"), _P("baumannlaan"), _P("dordtselaan")]
    volgorde = ["baumannlaan", "dordtselaan", "mahoniestraat"]
    gesorteerd = state.sorteer_op_volgorde(panden, volgorde)
    assert [p.slug for p in gesorteerd] == ["baumannlaan", "dordtselaan", "mahoniestraat"]


def test_onbekende_slug_komt_achteraan_stabiel():
    # "menkemaborgstraat" staat (nog) niet in de opgeslagen volgorde -> achteraan,
    # met behoud van de oorspronkelijke onderlinge volgorde van onbekende panden.
    panden = [_P("mahoniestraat"), _P("menkemaborgstraat"), _P("baumannlaan"), _P("nieuwstraat")]
    volgorde = ["baumannlaan", "mahoniestraat"]
    gesorteerd = state.sorteer_op_volgorde(panden, volgorde)
    assert [p.slug for p in gesorteerd] == ["baumannlaan", "mahoniestraat", "menkemaborgstraat", "nieuwstraat"]


def test_lege_volgorde_laat_oorspronkelijke_volgorde_intact():
    panden = [_P("a"), _P("b"), _P("c")]
    assert [p.slug for p in state.sorteer_op_volgorde(panden, [])] == ["a", "b", "c"]

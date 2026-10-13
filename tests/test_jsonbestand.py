"""Tests voor het atomair schrijven van JSON-state."""
import json

from rotterdam_scanner.jsonbestand import schrijf_json_atomisch


def test_schrijft_en_leest_terug(tmp_path):
    pad = tmp_path / "x.json"
    schrijf_json_atomisch(pad, {"a": 1, "b": [2, 3]})
    assert json.loads(pad.read_text(encoding="utf-8")) == {"a": 1, "b": [2, 3]}


def test_maakt_ontbrekende_map_aan(tmp_path):
    pad = tmp_path / "diep" / "er" / "y.json"
    schrijf_json_atomisch(pad, {"ok": True})
    assert pad.exists()
    assert json.loads(pad.read_text(encoding="utf-8")) == {"ok": True}


def test_overschrijft_bestaand_bestand_volledig(tmp_path):
    pad = tmp_path / "z.json"
    schrijf_json_atomisch(pad, {"oud": "data", "x": 1})
    schrijf_json_atomisch(pad, {"nieuw": "data"})
    assert json.loads(pad.read_text(encoding="utf-8")) == {"nieuw": "data"}


def test_laat_geen_temp_bestanden_achter(tmp_path):
    pad = tmp_path / "w.json"
    schrijf_json_atomisch(pad, {"k": "v"})
    overig = [p.name for p in tmp_path.iterdir() if p.name != "w.json"]
    assert overig == []  # geen *.tmp rommel


def test_mislukte_serialisatie_laat_oud_bestand_heel(tmp_path):
    pad = tmp_path / "v.json"
    schrijf_json_atomisch(pad, {"geldig": 1})

    class NietSerialiseerbaar:
        pass

    try:
        schrijf_json_atomisch(pad, {"kapot": NietSerialiseerbaar()})
    except TypeError:
        pass
    else:
        raise AssertionError("verwachtte een TypeError bij niet-serialiseerbare data")

    # Het oude bestand moet onaangeroerd zijn en er mag geen temp-rommel liggen.
    assert json.loads(pad.read_text(encoding="utf-8")) == {"geldig": 1}
    overig = [p.name for p in tmp_path.iterdir() if p.name != "v.json"]
    assert overig == []

"""Tests voor de Domivest-rentescraper (domivest_rente.py) en de dagelijkse
rente-bijwerking (rente_update.py). Geen echt netwerk: we parsen een opgeslagen
HTML-fragment en monkeypatchen het ophalen."""
import json

import pytest

from rotterdam_scanner import domivest_rente, rente_update
from rotterdam_scanner.config import Config

# Verkort maar structuurgelijk fragment van https://domivest.com/rente (de eerste
# tabel is de rentematrix; er staat bewust nog een tweede tabel achter om te toetsen
# dat we de juiste pakken).
_HTML = """
<h1>Rente</h1>
<figure class="table"><table class="blue">
<thead><tr><th>Perioden</th><th>t/m 50% LTV</th><th>t/m 60% LTV</th>
<th>t/m 65% LTV</th><th>t/m 70% LTV</th><th>t/m 75% LTV</th><th>t/m 80% LTV</th></tr></thead>
<tbody>
<tr><td>1 jaar</td><td>5,95%</td><td>5,95%</td><td>6,00%</td><td>6,05%</td><td>6,15%</td><td>6,25%</td></tr>
<tr><td>3 Jaar</td><td>6,05%</td><td>6,05%</td><td>6,10%</td><td>6,15%</td><td>6,25%</td><td>6,35%</td></tr>
<tr><td>5 Jaar</td><td>6,05%</td><td>6,05%</td><td>6,10%</td><td>6,15%</td><td>6,25%</td><td>6,35%</td></tr>
<tr><td>7 Jaar</td><td>6,00%</td><td>6,00%</td><td>6,05%</td><td>6,10%</td><td>6,20%</td><td>6,30%</td></tr>
<tr><td>10 Jaar</td><td>6,10%</td><td>6,10%</td><td>6,15%</td><td>6,20%</td><td>6,30%</td><td>6,40%</td></tr>
<tr><td>Variabel (3 maanden)</td><td>5,27%</td><td>5,27%</td><td>5,32%</td><td>5,37%</td><td>5,47%</td><td>5,57%</td></tr>
</tbody></table></figure>
<h2>Duurzaamheidskorting</h2>
<table class="blue"><tbody><tr><td>A++++</td><td>0,35%</td></tr></tbody></table>
"""


def test_parse_rentetabel_leest_periodes_en_ltv():
    tabel = domivest_rente.parse_rentetabel(_HTML)
    assert set(tabel) == {1, 3, 5, 7, 10, "variabel"}
    assert set(tabel[5]) == {50, 60, 65, 70, 75, 80}


def test_rente_voor_80procent_5jaar():
    tabel = domivest_rente.parse_rentetabel(_HTML)
    assert domivest_rente.rente_voor(tabel, 0.80, 5) == pytest.approx(0.0635)


def test_rente_voor_kiest_dekkende_ltv_klasse():
    tabel = domivest_rente.parse_rentetabel(_HTML)
    # 72% valt in de "t/m 75%"-klasse (5 jaar = 6,25%).
    assert domivest_rente.rente_voor(tabel, 0.72, 5) == pytest.approx(0.0625)
    # Precies op de grens blijft in die klasse.
    assert domivest_rente.rente_voor(tabel, 0.75, 5) == pytest.approx(0.0625)


def test_rente_voor_boven_hoogste_klasse_pakt_hoogste():
    tabel = domivest_rente.parse_rentetabel(_HTML)
    assert domivest_rente.rente_voor(tabel, 0.90, 5) == pytest.approx(0.0640) or \
        domivest_rente.rente_voor(tabel, 0.90, 5) == pytest.approx(0.0635)


def test_rente_voor_onbekende_periode_geeft_none():
    tabel = domivest_rente.parse_rentetabel(_HTML)
    assert domivest_rente.rente_voor(tabel, 0.80, 4) is None


def test_parse_onbruikbare_pagina_geeft_none():
    assert domivest_rente.parse_rentetabel("<html>geen tabel</html>") is None


def _config(tmp_path, **overrides):
    defaults = dict(
        gmail_address="s@e.com", gmail_app_password="x", report_to=["jmmreckman@gmail.com"],
        funda_mail_folder="INBOX", listing_expiry_days=30, opkoopbescherming_woz_grens=470_000,
        state_path=tmp_path / "state.json",
    )
    defaults.update(overrides)
    return Config(**defaults)


def test_werk_rente_bij_schrijft_nieuwe_rente_en_meldt_wijziging(tmp_path, monkeypatch):
    monkeypatch.setattr(domivest_rente, "actuele_rente", lambda *a, **k: 0.0635)
    config = _config(tmp_path)
    wijziging = rente_update.werk_rente_bij(config)
    assert wijziging is not None
    assert wijziging.nieuwe_rente == pytest.approx(0.0635)
    opgeslagen = json.loads((tmp_path / "reken_defaults.json").read_text())
    assert opgeslagen["rente"] == pytest.approx(0.0635)


def test_werk_rente_bij_laat_bar_en_overige_velden_staan(tmp_path, monkeypatch):
    (tmp_path / "reken_defaults.json").write_text(json.dumps({"rente": 0.058, "bar": 0.076, "ltv": 0.8}))
    monkeypatch.setattr(domivest_rente, "actuele_rente", lambda *a, **k: 0.0635)
    rente_update.werk_rente_bij(_config(tmp_path))
    opgeslagen = json.loads((tmp_path / "reken_defaults.json").read_text())
    assert opgeslagen["rente"] == pytest.approx(0.0635)
    assert opgeslagen["bar"] == pytest.approx(0.076)  # BAR ongemoeid
    assert opgeslagen["ltv"] == pytest.approx(0.8)


def test_werk_rente_bij_gebruikt_ltv_klasse_uit_defaults(tmp_path, monkeypatch):
    (tmp_path / "reken_defaults.json").write_text(json.dumps({"rente": 0.05, "ltv": 0.50}))
    gezien = {}
    def _fake(ltv, periode, url):
        gezien["ltv"] = ltv
        return 0.0605
    monkeypatch.setattr(domivest_rente, "actuele_rente", _fake)
    rente_update.werk_rente_bij(_config(tmp_path))
    assert gezien["ltv"] == pytest.approx(0.50)


def test_werk_rente_bij_geen_wijziging_geeft_none(tmp_path, monkeypatch):
    (tmp_path / "reken_defaults.json").write_text(json.dumps({"rente": 0.0635}))
    monkeypatch.setattr(domivest_rente, "actuele_rente", lambda *a, **k: 0.0635)
    assert rente_update.werk_rente_bij(_config(tmp_path)) is None


def test_werk_rente_bij_ophaalfout_verandert_niets(tmp_path, monkeypatch):
    (tmp_path / "reken_defaults.json").write_text(json.dumps({"rente": 0.058}))
    monkeypatch.setattr(domivest_rente, "actuele_rente", lambda *a, **k: None)
    assert rente_update.werk_rente_bij(_config(tmp_path)) is None
    opgeslagen = json.loads((tmp_path / "reken_defaults.json").read_text())
    assert opgeslagen["rente"] == pytest.approx(0.058)


def test_werk_rente_bij_uitgeschakeld_doet_niets(tmp_path, monkeypatch):
    monkeypatch.setattr(domivest_rente, "actuele_rente", lambda *a, **k: 0.0635)
    assert rente_update.werk_rente_bij(_config(tmp_path, domivest_rente_auto=False)) is None
    assert not (tmp_path / "reken_defaults.json").exists()

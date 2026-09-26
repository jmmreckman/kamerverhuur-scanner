"""Dagelijks de globale rente in het rekenmodel (kansen.steenhub.nl) gelijktrekken
met de actuele Domivest-verhuurhypotheekrente. De globale reken-defaults staan in
reken_defaults.json (naast state.json); die leest kansen_site/app.py ook, dus door
alleen de sleutel "rente" bij te werken volgt het rekenmodel automatisch.

We raken alleen "rente" aan - de BAR en de overige velden blijven staan wat de
gebruiker heeft ingevuld. Fail-safe: kan de rente niet worden opgehaald, dan
gebeurt er niets en blijft de bestaande rente ongewijzigd.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import domivest_rente
from .config import Config
from .investering import RekenUitgangspunten


# De rentegrafiek volgt bewust altijd één vaste cel (zodat de historie vergelijkbaar
# blijft, ongeacht wat er als globale LTV/looptijd in het model is ingesteld):
# Domivest, t/m 80% LTV, 5 jaar vast.
HISTORIE_LTV = 0.80
HISTORIE_PERIODE = 5

# Handmatig bijgehouden historie (Domivest 80% LTV, 5 jaar vast) uit een kladblok,
# als startpunt van de grafiek. Alleen maand+jaar was bekend, dus per punt de 1e van
# de maand. In april 2025 stonden twee noteringen (5,50% en later 5,30%); die zetten
# we op 1 en 16 april zodat beide zichtbaar blijven. Wordt eenmalig samengevoegd met
# de dagelijkse historie (zie backfill_historie) - bestaande datums blijven staan.
_HISTORISCHE_SEED: list[tuple[str, float]] = [
    ("2023-11-01", 0.0650),
    ("2023-12-01", 0.0625),
    ("2024-01-01", 0.0605),
    ("2024-03-01", 0.0615),
    ("2024-04-01", 0.0600),
    ("2024-06-01", 0.0615),
    ("2024-08-01", 0.0570),
    ("2024-09-01", 0.0545),
    ("2024-10-01", 0.0530),
    ("2025-02-01", 0.0540),
    ("2025-04-01", 0.0550),
    ("2025-04-16", 0.0530),
    ("2025-07-01", 0.0505),
    ("2025-12-01", 0.0530),
    ("2026-02-01", 0.0520),
    ("2026-03-01", 0.0565),
    ("2026-04-01", 0.0595),
    ("2026-09-01", 0.0635),
]


@dataclass(frozen=True)
class RenteWijziging:
    oude_rente: float
    nieuwe_rente: float
    ltv: float
    periode_jaren: object  # int of "variabel"


def _defaults_pad(config: Config) -> Path:
    return Path(config.state_path).parent / "reken_defaults.json"


def _historie_pad(config: Config) -> Path:
    return Path(config.state_path).parent / "rente_historie.json"


def laad_historie(config: Config) -> list[dict]:
    """De opgeslagen tijdreeks [{"datum": "YYYY-MM-DD", "rente": <fractie>}, ...],
    oplopend op datum. Leeg als er nog niets is genoteerd."""
    try:
        data = json.loads(_historie_pad(config).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    schoon = [
        {"datum": str(p["datum"]), "rente": float(p["rente"])}
        for p in data
        if isinstance(p, dict) and p.get("datum") and p.get("rente") is not None
    ]
    schoon.sort(key=lambda p: p["datum"])
    return schoon


def _schrijf_historie(config: Config, historie: list[dict]) -> None:
    pad = _historie_pad(config)
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text(json.dumps(historie, indent=2, ensure_ascii=False), encoding="utf-8")


def backfill_historie(config: Config) -> None:
    """Voegt de handmatig bijgehouden startpunten toe die nog niet in de historie
    staan. Idempotent: bestaande datums worden nooit overschreven of gedupliceerd,
    dus dit kan veilig bij elke run/paginabezoek draaien."""
    historie = laad_historie(config)
    aanwezig = {p["datum"] for p in historie}
    toegevoegd = False
    for datum, rente in _HISTORISCHE_SEED:
        if datum not in aanwezig:
            historie.append({"datum": datum, "rente": rente})
            toegevoegd = True
    if toegevoegd:
        historie.sort(key=lambda p: p["datum"])
        _schrijf_historie(config, historie)


def noteer_historie(config: Config, tabel: dict, datum_iso: str) -> float | None:
    """Noteert de rente van de vaste grafiekcel (80% LTV, 5 jaar) voor deze datum.
    Eén punt per dag: een tweede run op dezelfde dag overschrijft het punt i.p.v. te
    dupliceren. Geeft de genoteerde rente terug, of None als die niet te lezen was."""
    rente = domivest_rente.rente_voor(tabel, HISTORIE_LTV, HISTORIE_PERIODE)
    if rente is None:
        return None
    historie = laad_historie(config)
    for punt in historie:
        if punt["datum"] == datum_iso:
            punt["rente"] = rente
            break
    else:
        historie.append({"datum": datum_iso, "rente": rente})
    historie.sort(key=lambda p: p["datum"])
    _schrijf_historie(config, historie)
    return rente


def _laad_defaults(config: Config) -> dict:
    try:
        data = json.loads(_defaults_pad(config).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _schrijf_defaults(config: Config, defaults: dict) -> None:
    pad = _defaults_pad(config)
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text(json.dumps(defaults, indent=2, ensure_ascii=False), encoding="utf-8")


def werk_rente_bij(config: Config, tabel: dict | None = None) -> RenteWijziging | None:
    """Zet de globale rente in het rekenmodel gelijk aan de actuele Domivest-rente voor
    de ingestelde LTV-klasse + rentevaste periode, als die is veranderd. Met een al
    opgehaalde `tabel` wordt niet opnieuw gefetcht (zo delen historie + model-update
    één ophaalactie). Geeft de wijziging terug (voor de e-mailmelding) of None als er
    niets veranderde of de rente niet kon worden opgehaald."""
    if not config.domivest_rente_auto:
        return None

    defaults = _laad_defaults(config)
    basis = RekenUitgangspunten(koopsom=0, aantal_kamers=0)
    # LTV bepaalt welke "t/m X% LTV"-kolom we pakken; val terug op de modelstandaard.
    ltv = defaults.get("ltv", basis.ltv)
    try:
        ltv = float(ltv)
    except (TypeError, ValueError):
        ltv = basis.ltv

    if tabel is None:
        nieuwe = domivest_rente.actuele_rente(
            ltv, config.domivest_rente_periode_jaren, config.domivest_rente_url,
        )
    else:
        nieuwe = domivest_rente.rente_voor(tabel, ltv, config.domivest_rente_periode_jaren)
    if nieuwe is None:
        return None

    oude = defaults.get("rente", basis.rente)
    try:
        oude = float(oude)
    except (TypeError, ValueError):
        oude = basis.rente

    if abs(nieuwe - oude) < 1e-9:
        return None

    defaults["rente"] = nieuwe
    _schrijf_defaults(config, defaults)
    return RenteWijziging(
        oude_rente=oude, nieuwe_rente=nieuwe, ltv=ltv,
        periode_jaren=config.domivest_rente_periode_jaren,
    )

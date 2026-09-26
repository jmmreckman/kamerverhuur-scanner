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


@dataclass(frozen=True)
class RenteWijziging:
    oude_rente: float
    nieuwe_rente: float
    ltv: float
    periode_jaren: object  # int of "variabel"


def _defaults_pad(config: Config) -> Path:
    return Path(config.state_path).parent / "reken_defaults.json"


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


def werk_rente_bij(config: Config) -> RenteWijziging | None:
    """Haalt de actuele Domivest-rente op voor de ingestelde LTV-klasse + rentevaste
    periode en zet 'm als globale rente als die is veranderd. Geeft de wijziging
    terug (voor de e-mailmelding) of None als er niets is veranderd of de rente niet
    kon worden opgehaald."""
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

    nieuwe = domivest_rente.actuele_rente(
        ltv, config.domivest_rente_periode_jaren, config.domivest_rente_url,
    )
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

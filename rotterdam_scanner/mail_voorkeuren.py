"""Per-account mailvoorkeuren voor kansen.steenhub.nl. Elk ingelogd account zet zijn
eigen mailadres en vinkt per mailing (dagelijkse kansen, rentewijzigingen, ...) aan
of het die wil ontvangen. Opgeslagen in mail_voorkeuren.json naast state.json, zodat
zowel de website (instellen) als de dagelijkse run (versturen) erbij kan.

De ontvangers van elke mailing komen hieruit - niet meer uit de REPORT_TO-env. Die
env dient alleen nog als terugval zolang nog niemand voorkeuren heeft ingesteld, zodat
er na een deploy nooit ineens niemand meer mail krijgt.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .config import Config

# De beschikbare mailings: (sleutel, korte naam, uitleg). Nieuwe mailings later hier
# toevoegen - de pagina en de ontvangerslogica pikken ze automatisch op.
MAILINGS: list[tuple[str, str, str]] = [
    ("dagelijkse_kansen", "Dagelijkse kansen",
     "Het dagelijkse overzicht van nieuwe en openstaande kansen."),
    ("rente_updates", "Rentewijzigingen",
     "Een melding zodra de Domivest-verhuurhypotheekrente verandert."),
]
MAILING_KEYS = [sleutel for sleutel, _naam, _uitleg in MAILINGS]

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def geldig_email(waarde: str) -> bool:
    return bool(_EMAIL_RE.match((waarde or "").strip()))


def _pad(config: Config) -> Path:
    return Path(config.state_path).parent / "mail_voorkeuren.json"


def laad(config: Config) -> dict:
    try:
        data = json.loads(_pad(config).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("gebruikers", {})
    return data


def _schrijf(config: Config, data: dict) -> None:
    pad = _pad(config)
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def voorkeuren_voor(config: Config, gebruiker: str) -> dict:
    """De opgeslagen voorkeuren van dit account, of nette standaarden (leeg mailadres,
    alle mailings aan) als er nog niets is ingesteld - voor het tonen op de pagina."""
    opgeslagen = laad(config).get("gebruikers", {}).get(gebruiker)
    if not isinstance(opgeslagen, dict):
        return {"email": "", **{k: True for k in MAILING_KEYS}}
    resultaat = {"email": str(opgeslagen.get("email", ""))}
    for k in MAILING_KEYS:
        resultaat[k] = bool(opgeslagen.get(k, False))
    return resultaat


def zet_voorkeuren(config: Config, gebruiker: str, email: str, actieve_keys) -> None:
    actief = set(actieve_keys)
    data = laad(config)
    data["gebruikers"][gebruiker] = {
        "email": (email or "").strip(),
        **{k: (k in actief) for k in MAILING_KEYS},
    }
    _schrijf(config, data)


def ontvangers_voor(config: Config, mailing_key: str) -> list[str]:
    """De mailadressen die deze mailing willen ontvangen. Terugval op config.report_to
    zolang nog geen enkel account voorkeuren heeft ingesteld."""
    gebruikers = laad(config).get("gebruikers", {})
    if not gebruikers:
        # Nog niemand ingesteld: gebruik de oude env-lijst (dedupe, behoud volgorde).
        return list(dict.fromkeys(config.report_to))
    ontvangers = [
        prefs["email"].strip()
        for prefs in gebruikers.values()
        if isinstance(prefs, dict)
        and prefs.get(mailing_key)
        and geldig_email(prefs.get("email", ""))
    ]
    return sorted(set(ontvangers))

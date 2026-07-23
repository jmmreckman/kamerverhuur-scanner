"""AI-uitlezen van geuploade documenten (ID/paspoort, bewijs van inkomen/
garantsteller, bewijs van inschrijving) bij een documentverzoek (zie
webapp/documentverzoek.py) - haalt naam, geboortedatum, geboorteplaats,
studierichting en studentnummer uit de documenten, zodat de rest van het
concept-huurcontract automatisch aangevuld kan worden (zie webapp/app.py:
_verwerk_documenten_met_ai()). Gebruikt Claude's vision-/documentmogelijk-
heden (image/PDF content-blocks) via dezelfde Anthropic SDK als
ai_client.py - optioneel, alleen actief als ANTHROPIC_API_KEY gezet is."""
from __future__ import annotations

import base64
import json
import logging

import anthropic

from .config import Config

logger = logging.getLogger(__name__)

_ONDERSTEUNDE_MIMETYPES = {"application/pdf", "image/jpeg", "image/png", "image/webp", "image/gif"}

_SYSTEM_PROMPT = (
    "Je haalt persoonsgegevens uit gescande identiteitsdocumenten (ID-kaart/paspoort) en "
    "inschrijvingsbewijzen van een universiteit/hogeschool, ten behoeve van een Nederlands "
    "huurcontract. Antwoord ALLEEN met geldige JSON, zonder uitleg of markdown-opmaak, met exact "
    "deze velden (gebruik null als iets niet leesbaar of niet aanwezig is in de bijgevoegde "
    "bestanden):\n"
    '{"volledige_naam": str|null, "geboortedatum": str|null, "geboorteplaats": str|null, '
    '"studierichting": str|null, "studentnummer": str|null}\n\n'
    "Haal volledige_naam, geboortedatum (formaat DD-MM-JJJJ) en geboorteplaats uit het ID-document "
    "of paspoort. Haal studierichting en studentnummer uit het bewijs van inschrijving, indien "
    "bijgevoegd. Vul een veld nooit met een gok - gebruik null als je het niet zeker kunt aflezen."
)


class DocumentAIError(RuntimeError):
    """AI-uitlezen is niet geconfigureerd, of de aanvraag is mislukt."""


def _content_blok(mimetype: str, inhoud: bytes) -> dict:
    data = base64.b64encode(inhoud).decode("ascii")
    if mimetype == "application/pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": mimetype, "data": data}}
    return {"type": "image", "source": {"type": "base64", "media_type": mimetype, "data": data}}


def lees_documenten_uit(config: Config, documenten: list[tuple[str, str, bytes]]) -> dict:
    """`documenten` is een lijst van (bestandsnaam, mimetype, inhoud)-tuples.
    Geeft een dict terug met de uitgelezen velden (zie _SYSTEM_PROMPT hierboven).
    Gooit DocumentAIError als er geen API-key is, geen (ondersteund) bestand
    is meegegeven, of de aanvraag zelf mislukt."""
    if not config.anthropic_api_key:
        raise DocumentAIError("AI-uitlezen is nog niet ingesteld - vul ANTHROPIC_API_KEY in .env in.")

    content: list[dict] = []
    for bestandsnaam, mimetype, inhoud in documenten:
        if mimetype not in _ONDERSTEUNDE_MIMETYPES:
            continue
        content.append(_content_blok(mimetype, inhoud))
        content.append({"type": "text", "text": f"(bovenstaand bestand heet: {bestandsnaam})"})
    if not content:
        raise DocumentAIError("Geen ondersteunde documenten om uit te lezen (alleen PDF/JPEG/PNG/WEBP/GIF).")

    try:
        client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        respons = client.messages.create(
            model=config.anthropic_model, max_tokens=1024, system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.APIError as exc:
        raise DocumentAIError(f"AI-uitlezen is mislukt: {exc}") from exc

    tekst = "".join(blok.text for blok in respons.content if blok.type == "text").strip()
    tekst = tekst.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        geparsed = json.loads(tekst)
    except json.JSONDecodeError as exc:
        logger.warning("AI-uitlezen gaf geen geldige JSON terug: %s", tekst[:500])
        raise DocumentAIError("AI gaf geen leesbaar resultaat terug - probeer het later nog eens.") from exc
    if not isinstance(geparsed, dict):
        raise DocumentAIError("AI gaf geen leesbaar resultaat terug - probeer het later nog eens.")
    return geparsed


def vergelijk_met_aanmelding(ai_resultaat: dict, naam: str, studie: str, studentnummer: str) -> list[str]:
    """Vergelijkt wat de AI uit de documenten heeft gehaald met wat de
    kandidaat zelf in de aanmelding heeft ingevuld - geeft een lijst
    leesbare meldingen terug voor elk veld dat niet overeenkomt (leeg als
    alles overeenkomt, of als een van beide kanten niets invulde om te
    vergelijken)."""
    mismatches = []
    ai_naam = (ai_resultaat.get("volledige_naam") or "").strip()
    if ai_naam and naam and ai_naam.lower() != naam.strip().lower():
        mismatches.append(f"Naam op ID ('{ai_naam}') komt niet overeen met de aanmelding ('{naam}').")
    ai_studentnummer = (ai_resultaat.get("studentnummer") or "").strip()
    if ai_studentnummer and studentnummer and ai_studentnummer != studentnummer.strip():
        mismatches.append(
            f"Studentnummer op het inschrijvingsbewijs ('{ai_studentnummer}') komt niet overeen met "
            f"de aanmelding ('{studentnummer}')."
        )
    ai_studie = (ai_resultaat.get("studierichting") or "").strip()
    if ai_studie and studie and ai_studie.lower() != studie.strip().lower():
        mismatches.append(
            f"Studierichting op het inschrijvingsbewijs ('{ai_studie}') komt niet overeen met "
            f"de aanmelding ('{studie}')."
        )
    return mismatches

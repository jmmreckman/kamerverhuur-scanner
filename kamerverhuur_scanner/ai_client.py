"""AI-sparpaneel bij "Communicatie" op de huurderspagina (zie
webapp/communicatie.py): laat de beheerder met Claude sparren over een
lastige/emotionele huurderreactie, met het huurderprofiel en de
communicatiegeschiedenis automatisch als context - optioneel, alleen actief
als ANTHROPIC_API_KEY gezet is."""
from __future__ import annotations

import anthropic

from .config import Config

_SYSTEM_PROMPT = (
    "Je helpt een Nederlandse kamerverhuurder (student housing) bij het opstellen van "
    "reacties op huurders. Doel: zakelijk, feitelijk kloppend, effectief en transparant "
    "voorspelbaar - grenzen bewaken zonder onnodig te escaleren, geen ongefundeerde "
    "toezeggingen. Sommige huurders sturen lange, emotionele klaagmails; blijf dan vooral "
    "kalm, beknopt en to-the-point. Schrijf in het Nederlands, tenzij de huurder in het "
    "Engels schrijft - stel dan een Engelse reactie voor. Stel een concept-reactie op, en "
    "verwerk de aanwijzingen van de beheerder in de vervolgberichten."
)


class AIError(RuntimeError):
    """AI-sparren is niet geconfigureerd, of de aanvraag is mislukt."""


def genereer_reactie(
    config: Config, huurderprofiel: str, communicatiegeschiedenis: str, chatgeschiedenis: list[dict],
) -> str:
    """Stuurt het huurderprofiel en de recente communicatiegeschiedenis als
    context mee, gevolgd door chatgeschiedenis (afwisselend role "user"/
    "assistant", content als platte tekst - het laatste bericht moet van de
    beheerder zijn), en geeft het volgende AI-antwoord terug als platte tekst."""
    if not config.anthropic_api_key:
        raise AIError("AI-sparren is nog niet ingesteld - vul ANTHROPIC_API_KEY in .env in.")
    if not chatgeschiedenis:
        raise AIError("Geen bericht om naar de AI te sturen.")

    system = _SYSTEM_PROMPT + f"\n\nProfiel van deze huurder: {huurderprofiel or '(nog geen profiel ingevuld)'}"
    if communicatiegeschiedenis:
        system += f"\n\nEerdere communicatie met deze huurder (nieuwste onderaan):\n{communicatiegeschiedenis}"

    try:
        client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        respons = client.messages.create(
            model=config.anthropic_model, max_tokens=1024, system=system, messages=chatgeschiedenis,
        )
    except anthropic.APIError as exc:
        raise AIError(f"AI-aanvraag is mislukt: {exc}") from exc
    return "".join(blok.text for blok in respons.content if blok.type == "text").strip()

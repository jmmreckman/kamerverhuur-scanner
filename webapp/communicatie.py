"""Communicatiegeschiedenis en AI-sparpaneel op de huurderspagina: een
tijdlijn van in-/uitgaande communicatie per kamer, plus een chatvenster waarin
de beheerder met Claude kan sparren over een reactie - met het huurderprofiel
en de recente geschiedenis automatisch als context. Alleen de uiteindelijk
verstuurde mail (via "Versturen") komt in de tijdlijn terecht; het gespar zelf
wordt nergens opgeslagen."""
from __future__ import annotations

import json

_MAX_GESCHIEDENIS_VOOR_AI = 20  # voorkomt onbegrensde/dure AI-aanvragen bij een lange geschiedenis


class CommunicatieFout(ValueError):
    pass


def parse_chatgeschiedenis(ruw: str) -> list[dict]:
    """Parseert de hidden-field JSON met de chat tot nu toe - defensief, want
    dit veld gaat elke ronde als platte tekst heen en terug door de browser."""
    if not ruw:
        return []
    try:
        chatgeschiedenis = json.loads(ruw)
    except json.JSONDecodeError as exc:
        raise CommunicatieFout("Ongeldige chatgeschiedenis - begin opnieuw met sparren.") from exc
    if not isinstance(chatgeschiedenis, list) or not all(
        isinstance(b, dict) and b.get("role") in ("user", "assistant") and isinstance(b.get("content"), str)
        for b in chatgeschiedenis
    ):
        raise CommunicatieFout("Ongeldige chatgeschiedenis - begin opnieuw met sparren.")
    return chatgeschiedenis


def serialiseer_chatgeschiedenis(chatgeschiedenis: list[dict]) -> str:
    return json.dumps(chatgeschiedenis)


def formatteer_geschiedenis_voor_ai(rijen: list[list[str]]) -> str:
    """Zet de rauwe rijen uit SheetClient.get_communicatie() om in een platte
    tekstblok voor de AI-context - beperkt tot de meest recente regels, zodat
    een lange geschiedenis niet onbegrensd duur/traag wordt."""
    recent = rijen[-_MAX_GESCHIEDENIS_VOOR_AI:]
    regels = []
    for datum, _kamer, _huurder, richting, onderwerp, tekst in recent:
        kop = f"[{datum}] {richting}"
        if onderwerp:
            kop += f" - {onderwerp}"
        regels.append(f"{kop}\n{tekst}")
    return "\n\n".join(regels)

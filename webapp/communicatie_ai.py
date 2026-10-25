"""AI-hulp voor de communicatiemodule: conceptantwoorden aan huurders en een
doorlopende samenvatting per huurder, via de bestaande Anthropic-koppeling
(zelfde patroon als kamerverhuur_scanner/document_ai.py).

Opzet: de *pure* delen (stijl-nacheck, stopwoord-detectie, prompt-bouw en het
formatteren van de gesprekshistorie) staan los van de Claude-aanroep, zodat ze
in de sandbox getest kunnen worden zonder API-key of netwerk. `genereer_*` zijn
dunne wrappers die Claude aanroepen en daarna de stijl-nacheck toepassen.

Stijlregels (hard, afspraak met de gebruiker): helder/direct/informeel-
professioneel, GEEN puntkomma's, GEEN lange gedachtestreepjes, en geen typische
AI-stopwoorden. De systeemprompt vraagt dit al; `schoon_stijl()` haalt er daarna
alsnog de leestekens uit en `vind_ai_stopwoorden()` markeert verdachte frases
zodat je ze bij het goedkeuren ziet.
"""
from __future__ import annotations

import logging
import re

from kamerverhuur_scanner.config import Config

logger = logging.getLogger(__name__)


class CommunicatieAIError(RuntimeError):
    """AI is niet geconfigureerd, of de aanvraag is mislukt."""


SYSTEEM_STIJL = (
    "Schrijf helder, direct en informeel-professioneel, passend bij het beheren van "
    "studentenkamers. Gebruik GEEN puntkomma's en GEEN lange gedachtestreepjes. Vermijd "
    "typische AI-stopwoorden zoals \"Uiteraard\", \"In afwachting van je reactie\" en \"Ik "
    "sta voor je klaar\". Houd zinnen vlot en natuurlijk. Schrijf in het Nederlands, tenzij "
    "de huurder duidelijk in een andere taal schrijft - volg dan die taal."
)

_SYSTEEM_ANTWOORD = (
    "Je bent de beheerder van studentenkamers (Steenhub) en schrijft een kort, concreet "
    "antwoord aan een huurder op basis van de gesprekshistorie. Schrijf alleen de mailtekst "
    "zelf, geen onderwerp en geen uitleg vooraf. Begin met een passende aanhef en eindig met "
    "een normale afsluiting.\n\n" + SYSTEEM_STIJL
)

_SYSTEEM_SAMENVATTING = (
    "Je vat de communicatiegeschiedenis met een huurder samen voor de verhuurder, zodat die "
    "in een oogopslag weet wat er speelt en speelde. Noem lopende zaken, gemaakte afspraken en "
    "terugkerende punten, met data of jaartallen waar relevant. Kort en feitelijk, als bullets. "
    "Verzin niets - gebruik alleen wat in de berichten staat.\n\n" + SYSTEEM_STIJL
)

# AI-stopwoorden/frases die we markeren (kleine, bewuste lijst om valse treffers
# te voorkomen). Matcht hoofdletterongevoelig.
_STOPWOORDEN = (
    "uiteraard",
    "in afwachting van je reactie",
    "in afwachting van uw reactie",
    "ik sta voor je klaar",
    "ik sta voor u klaar",
    "aarzel niet",
    "schroom niet",
    "mocht je nog vragen hebben, dan hoor ik het graag",
)


def schoon_stijl(tekst: str) -> str:
    """Haalt puntkomma's en lange/korte gedachtestreepjes eruit en ruimt de
    leestekens/spaties op die daardoor kunnen ontstaan. Veilig vangnet bovenop
    de systeemprompt - verandert de inhoud niet, alleen de interpunctie."""
    if not tekst:
        return tekst
    t = tekst
    # Gedachtestreepjes (em/en-dash) als terzijde -> komma; puntkomma -> komma.
    t = t.replace(" — ", ", ").replace(" – ", ", ")
    t = t.replace("—", ", ").replace("–", ", ")
    t = t.replace(";", ",")
    # Opruimen: spatie vóór komma, dubbele komma's, komma gevolgd door punt, dubbele spaties.
    t = re.sub(r"\s+,", ",", t)
    t = re.sub(r",(?=\S)", ", ", t)
    t = re.sub(r"(,\s*){2,}", ", ", t)
    t = re.sub(r",\s*\.", ".", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t


def vind_ai_stopwoorden(tekst: str) -> list[str]:
    """Geeft de AI-stopwoorden/frases terug die in de tekst voorkomen
    (hoofdletterongevoelig), zodat je ze bij het goedkeuren ziet."""
    laag = (tekst or "").lower()
    return [w for w in _STOPWOORDEN if w in laag]


def formatteer_geschiedenis(berichten) -> str:
    """Zet een lijst berichten (sqlite-Row of dict met velden datum, richting,
    van, onderwerp, body) om in een leesbaar transcript voor in de prompt."""
    regels = []
    for b in berichten:
        datum = (_veld(b, "datum") or "")[:10]
        richting = _veld(b, "richting")
        van = _veld(b, "van") or ""
        wie = f"Huurder ({van})" if richting == "in" else "Beheerder (jij)"
        onderwerp = _veld(b, "onderwerp")
        body = (_veld(b, "body") or "").strip()
        kop = f"[{datum}] {wie}"
        if onderwerp:
            kop += f" - onderwerp: {onderwerp}"
        regels.append(f"{kop}\n{body}")
    return "\n\n".join(regels)


def bouw_antwoord_prompt(
    *, pand_naam: str, huurder_naam: str, geschiedenis_tekst: str, extra_instructie: str | None = None
) -> tuple[str, str]:
    """Geeft (systeemprompt, user-tekst) voor een conceptantwoord terug - pure
    string-bouw, los testbaar."""
    user = (
        f"Pand: {pand_naam}\nHuurder: {huurder_naam}\n\n"
        f"Gesprekshistorie (oudste eerst):\n{geschiedenis_tekst or '(nog geen eerdere berichten)'}\n\n"
    )
    if extra_instructie:
        user += f"Extra aanwijzing voor dit antwoord: {extra_instructie}\n\n"
    user += "Schrijf nu het conceptantwoord aan de huurder."
    return _SYSTEEM_ANTWOORD, user


def bouw_samenvatting_prompt(*, huurder_naam: str, geschiedenis_tekst: str) -> tuple[str, str]:
    user = (
        f"Huurder: {huurder_naam}\n\n"
        f"Alle communicatie (oudste eerst):\n{geschiedenis_tekst or '(geen berichten)'}\n\n"
        "Geef nu de samenvatting."
    )
    return _SYSTEEM_SAMENVATTING, user


def genereer_antwoord(
    config: Config, *, pand_naam: str, huurder_naam: str, berichten,
    extra_instructie: str | None = None,
) -> str:
    """Genereert een conceptantwoord (mailtekst) en past de stijl-nacheck toe."""
    systeem, user = bouw_antwoord_prompt(
        pand_naam=pand_naam, huurder_naam=huurder_naam,
        geschiedenis_tekst=formatteer_geschiedenis(berichten),
        extra_instructie=extra_instructie,
    )
    return schoon_stijl(_vraag_claude(config, systeem, user, max_tokens=1024))


def genereer_samenvatting(config: Config, *, huurder_naam: str, berichten) -> str:
    systeem, user = bouw_samenvatting_prompt(
        huurder_naam=huurder_naam, geschiedenis_tekst=formatteer_geschiedenis(berichten),
    )
    return schoon_stijl(_vraag_claude(config, systeem, user, max_tokens=700))


# --- intern -----------------------------------------------------------------

def _vraag_claude(config: Config, systeem: str, user: str, *, max_tokens: int) -> str:
    if not config.anthropic_api_key:
        raise CommunicatieAIError(
            "AI is nog niet ingesteld - vul ANTHROPIC_API_KEY in .env in."
        )
    import anthropic  # lui geïmporteerd zodat de pure functies ook zonder de SDK testbaar zijn

    try:
        client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        respons = client.messages.create(
            model=config.anthropic_model, max_tokens=max_tokens, system=systeem,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.APIError as exc:
        raise CommunicatieAIError(f"AI-aanvraag is mislukt: {exc}") from exc
    return "".join(b.text for b in respons.content if b.type == "text").strip()


def _veld(rij, naam: str):
    """Leest een veld uit een sqlite-Row of dict."""
    try:
        return rij[naam]
    except (KeyError, IndexError):
        return None

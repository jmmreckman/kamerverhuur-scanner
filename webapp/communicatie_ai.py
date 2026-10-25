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

_SYSTEEM_VRAAG = (
    "Je bent de assistent van de beheerder van studentenkamers (Steenhub). Je beantwoordt een "
    "interne vraag van de beheerder over het dossier van een specifieke huurder, op basis van de "
    "meegegeven samenvatting en berichten. Baseer je uitsluitend op die informatie en verzin "
    "niets. Staat het antwoord niet in het dossier, zeg dat dan eerlijk in plaats van te gissen. "
    "Noem concrete data, bedragen en afspraken waar ze er zijn, en geef aan wanneer iets speelde. "
    "Dit is een interne vraag, dus schrijf GEEN e-mail en geen aanhef, gewoon een direct, bondig "
    "antwoord. Schrijf in het Nederlands."
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


# Voor een conceptantwoord gebruiken we niet de hele historie (bij een lange
# relatie zijn dat honderden berichten - te groot/traag voor een request), maar
# de samenvatting als achtergrond + de recentste berichten als directe context.
_RECENT_VOOR_ANTWOORD = 25


# Veelvoorkomende woorden die als zoekterm niks toevoegen (klein, bewust kort).
_STOPWOORDEN_ZOEK = {
    "deze", "dit", "dat", "voor", "maar", "niet", "ook", "naar", "over", "heeft",
    "hebben", "wordt", "worden", "omdat", "zodat", "even", "graag", "nog", "wel",
    "een", "het", "van", "met", "aan", "bij", "als", "dus", "wat", "hoi", "hallo",
    "beste", "groet", "groeten", "alvast", "bedankt", "zou", "kunnen", "hierbij",
    "mvg", "jullie", "onze", "jouw", "mijn",
}


def zoektermen(tekst: str, max_termen: int = 8) -> list[str]:
    """Haalt de meest kenmerkende woorden uit een tekst om op te zoeken in de
    historie: eigennamen (woord met hoofdletter, bv. 'Rietdijk') en langere
    woorden, minus veelvoorkomende stopwoorden. Puur en los testbaar."""
    termen: list[str] = []
    for w in re.findall(r"[A-Za-zÀ-ÿ'’\-]{3,}", tekst or ""):
        wl = w.lower()
        if wl in _STOPWOORDEN_ZOEK:
            continue
        if w[:1].isupper() or len(w) >= 6:  # eigennaam of een langer, specifiek woord
            if wl not in {t.lower() for t in termen}:
                termen.append(w)
    return termen[:max_termen]


def bouw_antwoord_prompt(
    *, pand_naam: str, huurder_naam: str, geschiedenis_tekst: str,
    extra_instructie: str | None = None, samenvatting: str | None = None,
    relevante_tekst: str | None = None,
) -> tuple[str, str]:
    """Geeft (systeemprompt, user-tekst) voor een conceptantwoord terug - pure
    string-bouw, los testbaar."""
    user = f"Pand: {pand_naam}\nHuurder: {huurder_naam}\n\n"
    if samenvatting:
        user += f"Achtergrond (samenvatting van de hele relatie met deze huurder):\n{samenvatting}\n\n"
    if relevante_tekst:
        user += (
            "Mogelijk relevante oudere berichten (teruggezocht op het onderwerp van dit "
            f"gesprek):\n{relevante_tekst}\n\n"
        )
    user += f"Recente berichten (oudste eerst):\n{geschiedenis_tekst or '(nog geen eerdere berichten)'}\n\n"
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


def bouw_vraag_prompt(
    *, pand_naam: str, huurder_naam: str, geschiedenis_tekst: str, vraag: str,
    samenvatting: str | None = None, relevante_tekst: str | None = None,
) -> tuple[str, str]:
    """Geeft (systeemprompt, user-tekst) voor het beantwoorden van een interne
    vraag over het dossier terug - pure string-bouw, los testbaar."""
    user = f"Pand: {pand_naam}\nHuurder: {huurder_naam}\n\n"
    if samenvatting:
        user += f"Samenvatting van het dossier:\n{samenvatting}\n\n"
    if relevante_tekst:
        user += (
            "Mogelijk relevante oudere berichten (teruggezocht op de vraag):\n"
            f"{relevante_tekst}\n\n"
        )
    user += f"Recente berichten (oudste eerst):\n{geschiedenis_tekst or '(nog geen berichten)'}\n\n"
    user += f"Vraag van de beheerder: {vraag}\n\nBeantwoord de vraag op basis van het dossier."
    return _SYSTEEM_VRAAG, user


def bouw_vakman_mail(
    *, vakman_naam: str, vak: str | None, huurder_naam: str, adres: str, reden: str,
    beheerder_telefoon: str = "",
) -> tuple[str, str]:
    """Bouwt de mail aan een klusjesman als vaste sjabloontekst (geen AI), zodat
    de vaste instructies - factuur rechtstreeks naar de beheerder, en boven 150
    euro eerst bellen - altijd exact kloppen. Geeft (onderwerp, body) terug; gaat
    daarna net als elk concept eerst naar de goedkeuringswachtrij, dus je kunt 'm
    nog aanpassen."""
    aanhef = vakman_naam or "beste"
    bel = f" Is het bedrag hoger dan 150 euro, bel me dan eerst even op {beheerder_telefoon}." if beheerder_telefoon \
        else " Is het bedrag hoger dan 150 euro, bel me dan eerst even voordat je het werk doet."
    body = (
        f"Hoi {aanhef},\n\n"
        f"Voor {adres} is er een klus: {reden}. {huurder_naam} neemt contact met je op om een "
        f"afspraak te maken, of neem zelf even contact op.\n\n"
        f"Graag de factuur rechtstreeks naar mij sturen.{bel}\n\n"
        f"Alvast bedankt, groeten"
    )
    return f"Klus op {adres}", schoon_stijl(body)


def genereer_antwoord(
    config: Config, *, pand_naam: str, huurder_naam: str, berichten,
    extra_instructie: str | None = None, samenvatting: str | None = None,
    relevante_berichten=None,
) -> str:
    """Genereert een conceptantwoord (mailtekst) en past de stijl-nacheck toe.
    Gebruikt de samenvatting als achtergrond + de recentste berichten, en - indien
    meegegeven - een set gericht teruggezochte, mogelijk relevante oudere berichten
    (bv. dat onderwerp van een half jaar geleden). Zo blijft de prompt klein/snel,
    maar wordt relevante oude context niet gemist."""
    recent = list(berichten)[-_RECENT_VOOR_ANTWOORD:]
    relevante_tekst = formatteer_geschiedenis(relevante_berichten) if relevante_berichten else None
    systeem, user = bouw_antwoord_prompt(
        pand_naam=pand_naam, huurder_naam=huurder_naam,
        geschiedenis_tekst=formatteer_geschiedenis(recent),
        extra_instructie=extra_instructie, samenvatting=samenvatting, relevante_tekst=relevante_tekst,
    )
    return schoon_stijl(_vraag_claude(config, systeem, user, max_tokens=2048))


def beantwoord_vraag(
    config: Config, *, pand_naam: str, huurder_naam: str, berichten, vraag: str,
    samenvatting: str | None = None, relevante_berichten=None,
) -> str:
    """Beantwoordt een interne vraag van de beheerder over het dossier van een
    huurder (geen e-mail, geen stijl-nacheck - het is een intern antwoord).
    Gebruikt dezelfde context als een conceptantwoord: de samenvatting + de
    recentste berichten + gericht teruggezochte, mogelijk relevante oudere
    berichten, zodat ook iets van langer geleden meegewogen wordt."""
    recent = list(berichten)[-_RECENT_VOOR_ANTWOORD:]
    relevante_tekst = formatteer_geschiedenis(relevante_berichten) if relevante_berichten else None
    systeem, user = bouw_vraag_prompt(
        pand_naam=pand_naam, huurder_naam=huurder_naam,
        geschiedenis_tekst=formatteer_geschiedenis(recent), vraag=vraag,
        samenvatting=samenvatting, relevante_tekst=relevante_tekst,
    )
    return _vraag_claude(config, systeem, user, max_tokens=1500).strip()


# Boven dit aantal tekens passen de berichten niet comfortabel in één
# AI-aanroep; dan vatten we in stukken samen en voegen we die samen (map-reduce),
# zodat ook een hele lange huurder-historie volledig meetelt.
_MAX_CHARS_SAMENVATTING = 40_000


def _chunk_berichten(berichten, max_chars: int) -> list[list]:
    """Hakt de berichtenlijst in opeenvolgende stukken waarvan de getekstte
    historie elk ongeveer onder `max_chars` blijft (chronologie behouden)."""
    chunks, huidig, lengte = [], [], 0
    for b in berichten:
        stuk = len(_veld(b, "body") or "") + 120  # +kop/overhead per bericht
        if huidig and lengte + stuk > max_chars:
            chunks.append(huidig)
            huidig, lengte = [], 0
        huidig.append(b)
        lengte += stuk
    if huidig:
        chunks.append(huidig)
    return chunks


def genereer_samenvatting(config: Config, *, huurder_naam: str, berichten) -> str:
    """Samenvatting per huurder. Bij een korte historie één AI-aanroep; bij een
    lange historie in stukken (deel-samenvattingen) die daarna tot één geheel
    worden samengevoegd, zodat de volledige geschiedenis meetelt."""
    volledig = formatteer_geschiedenis(berichten)
    if len(volledig) <= _MAX_CHARS_SAMENVATTING:
        systeem, user = bouw_samenvatting_prompt(huurder_naam=huurder_naam, geschiedenis_tekst=volledig)
        return schoon_stijl(_vraag_claude(config, systeem, user, max_tokens=2000))

    deel_samenvattingen = []
    chunks = _chunk_berichten(berichten, _MAX_CHARS_SAMENVATTING)
    for i, chunk in enumerate(chunks, 1):
        systeem, user = bouw_samenvatting_prompt(
            huurder_naam=huurder_naam, geschiedenis_tekst=formatteer_geschiedenis(chunk),
        )
        user += f"\n\n(Dit is deel {i} van {len(chunks)} van de historie.)"
        deel_samenvattingen.append(_vraag_claude(config, systeem, user, max_tokens=900))

    combineer_user = (
        f"Hieronder staan {len(deel_samenvattingen)} deelsamenvattingen van de communicatie met "
        f"{huurder_naam}, in chronologische volgorde. Voeg ze samen tot een enkele, heldere "
        "samenvatting zonder herhaling, met de lopende zaken, gemaakte afspraken en terugkerende "
        "punten (met data of jaartallen waar relevant):\n\n"
        + "\n\n---\n\n".join(deel_samenvattingen)
    )
    # Ruime tokenlimiet: bij een zware huurder (bv. Nushka) wil de samenvatting
    # langer zijn dan ~750 woorden - anders wordt het slot afgekapt.
    return schoon_stijl(_vraag_claude(config, _SYSTEEM_SAMENVATTING, combineer_user, max_tokens=2500))


def werk_samenvatting_bij(
    config: Config, *, huurder_naam: str, bestaande_samenvatting: str, nieuwe_berichten
) -> str:
    """Werkt een bestaande samenvatting incrementeel bij met alleen de nieuwe
    berichten (één AI-aanroep). Goedkoop en snel: de bestaande samenvatting gaat
    als basis mee en de nieuwe ontwikkelingen worden erin verwerkt, zodat het
    resultaat weer één volledige, samenhangende samenvatting is (geen losse
    aanplakstrook). Voor een volledige herberekening: genereer_samenvatting."""
    nieuw_tekst = formatteer_geschiedenis(nieuwe_berichten)
    user = (
        f"Hieronder staat de bestaande samenvatting van de communicatie met {huurder_naam}, "
        "gevolgd door de nieuwe berichten die daarna zijn binnengekomen. Werk de samenvatting "
        "bij: verwerk de nieuwe ontwikkelingen op de juiste plek, houd bestaande afspraken en "
        "lopende zaken intact, en lever opnieuw EEN volledige, heldere samenvatting (dus geen "
        "losse aanvulling onderaan en geen herhaling). Gebruik dezelfde opzet met kopjes.\n\n"
        f"=== BESTAANDE SAMENVATTING ===\n{bestaande_samenvatting}\n\n"
        f"=== NIEUWE BERICHTEN ===\n{nieuw_tekst}"
    )
    return schoon_stijl(_vraag_claude(config, _SYSTEEM_SAMENVATTING, user, max_tokens=2500))


# --- intern -----------------------------------------------------------------

def _vraag_claude(config: Config, systeem: str, user: str, *, max_tokens: int) -> str:
    if not config.anthropic_api_key:
        raise CommunicatieAIError(
            "AI is nog niet ingesteld - vul ANTHROPIC_API_KEY in .env in."
        )
    import anthropic  # lui geïmporteerd zodat de pure functies ook zonder de SDK testbaar zijn

    # Expliciete timeout + hooguit 1 retry, zodat een trage of rate-gelimiteerde
    # call ruim binnen de gunicorn-worker-timeout (120s) faalt met een nette
    # foutmelding, in plaats van dat de worker wordt gekild en de browser een
    # ERR_CONNECTION_ABORTED toont (geen antwoord). Worst case ~45+backoff+45s.
    try:
        client = anthropic.Anthropic(
            api_key=config.anthropic_api_key, timeout=45.0, max_retries=1
        )
        respons = client.messages.create(
            model=config.anthropic_model, max_tokens=max_tokens, system=systeem,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.APITimeoutError as exc:
        raise CommunicatieAIError(
            "De AI reageerde niet op tijd. Dit gebeurt als de server het druk heeft "
            "(bijvoorbeeld tijdens de Gmail-backfill). Probeer het zo nog eens."
        ) from exc
    except anthropic.APIError as exc:
        raise CommunicatieAIError(f"AI-aanvraag is mislukt: {exc}") from exc
    return "".join(b.text for b in respons.content if b.type == "text").strip()


def _veld(rij, naam: str):
    """Leest een veld uit een sqlite-Row of dict."""
    try:
        return rij[naam]
    except (KeyError, IndexError):
        return None

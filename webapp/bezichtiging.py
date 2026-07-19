"""Bezichtigingen inplannen voor geselecteerde aanmelders (reacties op de
aanbodpagina): tijdsloten berekenen, en de bevestigingsmail (aanmelder, Engels)
en overzichtsmail (beheerders, Nederlands) opstellen. Blijft bewust stateless -
net als de rest van de aanmeldingenflow wordt niets hiervan in de sheet
opgeslagen, alleen gemaild."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from kamerverhuur_scanner.models import Pand

_AANMELDER_VELDEN = ("kamer", "naam", "email", "telefoon", "bezichtiging", "videobel_nummer")
_AFSPRAAK_VELDEN = _AANMELDER_VELDEN + ("tijd_start", "tijd_eind")


class BezichtigingFout(ValueError):
    pass


def serialiseer_aanmelder(kamer: str, naam: str, email: str, telefoon: str, bezichtiging: str, videobel_nummer: str) -> str:
    """Codeert één aanmelder als waarde van een checkbox op de aanmeldingen-
    pagina - zo hoeft de rest van de flow niet terug de sheet in om deze
    gegevens opnieuw op te zoeken (dezelfde stijl als de bestaande "Contract
    maken"-link, die ook rauwe rijgegevens als URL-parameters meegeeft)."""
    return "|".join([kamer, naam, email, telefoon, bezichtiging, videobel_nummer])


def parse_aanmelder(ruw: str) -> dict:
    delen = ruw.split("|")
    if len(delen) != len(_AANMELDER_VELDEN):
        raise BezichtigingFout("Ongeldige aanmelder-gegevens - probeer opnieuw vanaf de aanmeldingenlijst.")
    return dict(zip(_AANMELDER_VELDEN, delen))


def serialiseer_afspraak(afspraak: dict) -> str:
    return "|".join(str(afspraak[veld]) for veld in _AFSPRAAK_VELDEN)


def parse_afspraak(ruw: str) -> dict:
    delen = ruw.split("|")
    if len(delen) != len(_AFSPRAAK_VELDEN):
        raise BezichtigingFout("Ongeldige afspraakgegevens - probeer opnieuw vanaf de aanmeldingenlijst.")
    return dict(zip(_AFSPRAAK_VELDEN, delen))


def bel_nummer(aanmelder: dict) -> str:
    """Het nummer dat gebeld moet worden: bij een video call het opgegeven
    video-bel-nummer (als dat is ingevuld), anders altijd het algemene
    telefoonnummer van de aanmelder."""
    if aanmelder["bezichtiging"] == "Video call" and aanmelder["videobel_nummer"]:
        return aanmelder["videobel_nummer"]
    return aanmelder["telefoon"]


def bereken_planning(aanmelders: list[dict], tijd_vanaf: time, duur_minuten: int) -> list[dict]:
    """Plant de aanmelders achter elkaar in, in de volgorde waarin ze zijn
    aangevinkt, elk `duur_minuten` lang vanaf tijd_vanaf. tijd_start/tijd_eind
    worden als "UU:MM"-string opgeslagen (i.p.v. een time-object), zodat ze
    zonder omwegen als hidden-veld door de rest van de flow heen kunnen."""
    basis = datetime.combine(date.today(), tijd_vanaf)
    afspraken = []
    for i, aanmelder in enumerate(aanmelders):
        start = basis + timedelta(minutes=i * duur_minuten)
        eind = start + timedelta(minutes=duur_minuten)
        afspraken.append({
            **aanmelder,
            "tijd_start": start.strftime("%H:%M"),
            "tijd_eind": eind.strftime("%H:%M"),
        })
    return afspraken


def bouw_bevestigingsmail(pand: Pand, afspraak: dict, datum: date) -> dict[str, str]:
    """De (Engelstalige) bevestigingsmail naar de aanmelder zelf, met locatie,
    datum, tijdstip en manier van bezichtigen."""
    adres = f"{pand.naam}, {pand.plaats}" if pand.plaats else pand.naam
    manier = (
        f"a video call - we will call you at {bel_nummer(afspraak)}"
        if afspraak["bezichtiging"] == "Video call"
        else f"an in-person viewing at {adres}"
    )
    onderwerp = f"Your viewing for room {afspraak['kamer']}, {pand.naam}"
    tekst = (
        f"Dear {afspraak['naam']},\n\n"
        f"Your viewing for room {afspraak['kamer']} at {pand.naam} has been scheduled:\n\n"
        f"Date: {datum.strftime('%d-%m-%Y')}\n"
        f"Time: {afspraak['tijd_start']} - {afspraak['tijd_eind']}\n"
        f"How: {manier}\n\n"
        "If anything changes on your end, just let us know by replying to this email.\n\n"
        "Kind regards,\nSteenhub"
    )
    return {"onderwerp": onderwerp, "tekst": tekst}


def bouw_overzichtsmail_beheerders(pand: Pand, afspraken: list[dict], datum: date) -> dict[str, str]:
    """Interne overzichtsmail naar alle beheerders met de volledige lijst
    ingeplande bezichtigingen - Nederlands, puur intern."""
    onderwerp = f"Bezichtigingen ingepland - {pand.naam}, {datum.strftime('%d-%m-%Y')}"
    regels = []
    for a in afspraken:
        manier = "videobellen" if a["bezichtiging"] == "Video call" else "in persoon"
        regels.append(
            f"- {a['tijd_start']}-{a['tijd_eind']}: {a['naam']} (kamer {a['kamer']}), {manier}, "
            f"te bellen op {bel_nummer(a)}, {a['email']}"
        )
    tekst = (
        f"Er zijn bezichtigingen ingepland voor {pand.naam} op {datum.strftime('%d-%m-%Y')}:\n\n"
        + "\n".join(regels)
        + "\n\n- Steenhub (automatisch bericht)"
    )
    return {"onderwerp": onderwerp, "tekst": tekst}

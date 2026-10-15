"""Bezichtigingen inplannen voor geselecteerde aanmelders (reacties op de
aanbodpagina): tijdsloten berekenen, en de bevestigingsmail (aanmelder, Engels)
en overzichtsmail (beheerders, Nederlands) opstellen. Bevestigde bezichtigingen
worden door SheetClient.add_bezichtiging() in het "Bezichtigingen"-tabblad
gelogd - hierdoor kan een latere ronde ("Bezichtigers toevoegen aan bestaande
lijst") een eerder geplande dag terugvinden en er verder op aansluiten
(zie groepeer_per_datum())."""
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


def vind_dubbele_emails(afspraken: list[dict], bestaande_emails: set[str]) -> set[str]:
    """Geeft de (genormaliseerde, lowercase) e-mailadressen terug waarvoor de
    beheerder gewaarschuwd moet worden vóór het versturen: adressen die
    vaker dan 1x voorkomen onder de aangevinkte aanmelders in dit voorstel,
    of die al eerder zijn uitgenodigd (staan in bestaande_emails, ongeacht
    op welke datum) - bv. iemand die het aanmeldformulier per ongeluk twee
    keer heeft ingevuld en zo ongemerkt twee keer wordt uitgenodigd."""
    tellingen: dict[str, int] = {}
    for afspraak in afspraken:
        email = (afspraak.get("email") or "").strip().lower()
        if email:
            tellingen[email] = tellingen.get(email, 0) + 1
    bestaand_genormaliseerd = {e.strip().lower() for e in bestaande_emails if e.strip()}
    return {email for email, aantal in tellingen.items() if aantal > 1 or email in bestaand_genormaliseerd}


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


def bouw_huurders_inlichten_mail(datum: date, tijd_vanaf: str, tijd_tot: str) -> dict[str, str]:
    """De (Engelstalige) mail naar de huidige huurders om ze op de hoogte te
    stellen van een ingeplande bezichtiging - ze hoeven zelf niets te doen,
    maar krijgen wel te horen dat er in de gemeenschappelijke ruimtes iemand
    rond kan lopen. Bedoeld als voorgevulde tekst voor "Mail het hele
    huishouden" (zie webapp/app.py: licht_huurders_in())."""
    onderwerp = f"Heads-up: room viewing on {datum.strftime('%d-%m-%Y')}"
    tekst = (
        "Hi all,\n\n"
        f"Just a heads-up: we have a room viewing scheduled on {datum.strftime('%d-%m-%Y')} "
        f"between {tijd_vanaf} and {tijd_tot}.\n\n"
        "You don't need to do anything for this - we won't come into your room, but please be "
        "aware that we (and the visitor(s)) may walk around in the shared/common areas "
        "(kitchen, hallway, etc.) during this time.\n\n"
        "Thanks,\nSteenhub"
    )
    return {"onderwerp": onderwerp, "tekst": tekst}


def groepeer_per_datum(rijen: list[list[str]]) -> dict[str, list[dict]]:
    """Groepeert de rauwe rijen uit SheetClient.get_bezichtigingen() per datum
    (ISO-notatie, "jjjj-mm-dd"), oplopend gesorteerd - zowel de datums
    onderling als de afspraken binnen elke datum (op tijd_start). Gebruikt om
    te bepalen welke bestaande lijsten er al zijn voor "Bezichtigers
    toevoegen aan bestaande lijst"."""
    per_datum: dict[str, list[dict]] = {}
    for row in rijen:
        datum, tijd_start, tijd_eind, kamer, naam, email, telefoon, manier, bel_nr, _bevestigd_op = row
        per_datum.setdefault(datum, []).append({
            "tijd_start": tijd_start, "tijd_eind": tijd_eind, "kamer": kamer, "naam": naam,
            "email": email, "telefoon": telefoon, "bezichtiging": manier, "bel_nummer": bel_nr,
        })
    for afspraken in per_datum.values():
        afspraken.sort(key=lambda a: a["tijd_start"])
    return dict(sorted(per_datum.items()))


def duur_minuten_van(afspraak: dict) -> int:
    start = datetime.strptime(afspraak["tijd_start"], "%H:%M")
    eind = datetime.strptime(afspraak["tijd_eind"], "%H:%M")
    return int((eind - start).total_seconds() // 60)


def bouw_overzichtsmail_beheerders(pand: Pand, afspraken: list[dict], datum: date) -> dict[str, str]:
    """Interne overzichtsmail naar alle beheerders met de volledige,
    actuele lijst ingeplande bezichtigingen voor deze datum (dus inclusief
    eerder al bevestigde bezichtigingen als dit een aanvulling is via
    "Bezichtigers toevoegen aan bestaande lijst") - Nederlands, puur intern.
    Verwacht dat `afspraak["bel_nummer"]` al gezet is (zowel verse afspraken
    als de rijen uit groepeer_per_datum() hebben dit al)."""
    onderwerp = f"Bezichtigingen ingepland - {pand.naam}, {datum.strftime('%d-%m-%Y')}"
    regels = []
    for a in afspraken:
        manier = "videobellen" if a["bezichtiging"] == "Video call" else "in persoon"
        regels.append(
            f"- {a['tijd_start']}-{a['tijd_eind']}: {a['naam']} (kamer {a['kamer']}), {manier}, "
            f"te bellen op {a['bel_nummer']}, {a['email']}"
        )
    tekst = (
        f"Er zijn bezichtigingen ingepland voor {pand.naam} op {datum.strftime('%d-%m-%Y')}:\n\n"
        + "\n".join(regels)
        + "\n\n- Steenhub (automatisch bericht)"
    )
    return {"onderwerp": onderwerp, "tekst": tekst}

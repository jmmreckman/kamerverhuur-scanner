#!/usr/bin/env python3
"""Dagelijkse inname (Fase 2) van de eigen Steenhub-mailboxen - zie
deploy/docker-compose.yml (service 'mail-inname') en webapp/mail_inname.py.

Twee mailboxen, elk 1x per dag uitgelezen:
- onderhoud@steenhub.nl   -> opent een onderhoudsticket bij de juiste huurder en
                             logt de mail eronder.
- communicatie@steenhub.nl -> logt de mail bij de huurder (kanaal communicatie) en
                             laat de AI beoordelen of een antwoord nodig is; zo ja,
                             komt er een concept in de goedkeuringswachtrij (niets
                             gaat automatisch de deur uit).

Koppeling aan de huurder: we zoeken in de hele mail (afzender, aan, cc, tekst)
naar een bekend huurder-adres. Zo werkt het ook als jij een mail doorstuurt (dan
ben jij immers de afzender). Vinden we geen huurder, dan komt de mail als
'nog koppelen'-item in de wachtrij in plaats van verloren te gaan.

Geen losse cron-daemon nodig: dit proces blijft zelf draaien, voert de inname
uit en wacht dan tot het volgende vaste tijdstip. Mailboxen zonder ingestelde
gebruiker/wachtwoord worden overgeslagen (de service doet dan simpelweg niets
voor die bak). Idempotent: al verwerkte mail (op Message-ID) wordt overgeslagen,
en een mail wordt pas als 'gelezen' gemarkeerd na succesvolle verwerking.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from kamerverhuur_scanner.config import Config, ConfigError
from webapp import communicatie_ai, communicatie_db, mail_inname

_TIJDZONE = ZoneInfo("Europe/Amsterdam")
_UUR_VAN_DE_DAG = 7  # 1x per dag, 's ochtends rond 07:00 Europe/Amsterdam.

logger = logging.getLogger("mail_inname")


def _seconden_tot_volgende_run(nu: datetime | None = None) -> float:
    """Tijd tot het eerstvolgende vaste tijdstip (vandaag of morgen om _UUR)."""
    nu = nu or datetime.now(_TIJDZONE)
    volgende = nu.replace(hour=_UUR_VAN_DE_DAG, minute=0, second=0, microsecond=0)
    if volgende <= nu:
        volgende += timedelta(days=1)
    return (volgende - nu).total_seconds()


def _pand_naam(config: Config, pand_slug: str | None) -> str:
    if not pand_slug:
        return ""
    try:
        from kamerverhuur_scanner.properties import load_properties
        for pand in load_properties(config.properties_file):
            if pand.slug == pand_slug:
                return pand.naam
    except Exception:  # noqa: BLE001
        pass
    return pand_slug


def _verwerk_mail(config: Config, db, soort: str, raw: bytes) -> str:
    """Verwerkt één mail. soort = 'onderhoud' of 'communicatie'. Geeft een korte
    statuscode terug voor de logging ('dup'/'onderhoud'/'communicatie'/'ongekoppeld')."""
    gegevens = mail_inname.parse_inkomend(raw)
    # Al eerder verwerkt? (idempotent, geen dubbele tickets bij heruitlezen.)
    if gegevens["message_id"] and communicatie_db.bericht_met_message_id(db, gegevens["message_id"]):
        return "dup"

    contact = None
    for adres in mail_inname.adressen_in_mail(raw):
        gevonden = communicatie_db.get_contact_op_email(db, adres)
        if gevonden is not None:
            contact = gevonden
            break

    if contact is None:
        # Niet te koppelen: als 'nog koppelen'-item in de wachtrij zetten en ook
        # als bericht vastleggen (zodat heruitlezen het op Message-ID overslaat).
        communicatie_db.voeg_bericht_toe(
            db, contact_id=None, pand_slug=None, kanaal=soort, richting="in",
            van=gegevens["van"], onderwerp=gegevens["onderwerp"], body=gegevens["body"],
            datum=gegevens["datum"], bron=f"mail-{soort}", message_id=gegevens["message_id"],
        )
        communicatie_db.maak_actie(
            db, type="inkomend-ongekoppeld", pand_slug=None, ontvanger=None,
            concept_onderwerp=gegevens["onderwerp"],
            concept_body=("Deze binnengekomen mail kon niet automatisch aan een huurder "
                          f"gekoppeld worden.\n\nVan: {gegevens['van']}\nAan: {gegevens['naar']}\n"
                          f"Kanaal: {soort}\n\n{gegevens['body']}"),
        )
        return "ongekoppeld"

    contact_id = int(contact["id"])
    pand_slug = contact["pand_slug"]
    naam = contact["naam"]

    if soort == "onderhoud":
        klus_id = communicatie_db.maak_klus(
            db, titel=(gegevens["onderwerp"] or "Onderhoud (via mail)"),
            pand_slug=pand_slug, contact_id=contact_id, kamer=contact["kamer"],
            omschrijving=gegevens["body"],
        )
        communicatie_db.voeg_bericht_toe(
            db, contact_id=contact_id, pand_slug=pand_slug, kanaal="onderhoud", richting="in",
            van=gegevens["van"], onderwerp=gegevens["onderwerp"], body=gegevens["body"],
            datum=gegevens["datum"], bron="mail-onderhoud", message_id=gegevens["message_id"],
            klus_id=klus_id,
        )
        return "onderhoud"

    # communicatie: loggen + AI laten beoordelen of er een antwoord nodig is.
    communicatie_db.voeg_bericht_toe(
        db, contact_id=contact_id, pand_slug=pand_slug, kanaal="communicatie", richting="in",
        van=gegevens["van"], onderwerp=gegevens["onderwerp"], body=gegevens["body"],
        datum=gegevens["datum"], bron="mail-communicatie", message_id=gegevens["message_id"],
    )
    try:
        antwoord_nodig, concept = communicatie_ai.beoordeel_inkomende_mail(
            config, pand_naam=_pand_naam(config, pand_slug), huurder_naam=naam,
            onderwerp=gegevens["onderwerp"], mail_tekst=gegevens["body"],
            samenvatting=contact["samenvatting"],
        )
    except communicatie_ai.CommunicatieAIError as exc:
        logger.warning("  AI-beoordeling mislukt voor %s: %s", naam, exc)
        antwoord_nodig, concept = False, None

    if antwoord_nodig and concept:
        ontvanger = (gegevens["van"] or "")
        emails = communicatie_db.emails_van_contact(db, contact_id)
        if emails:
            ontvanger = emails[0]
        onderwerp = gegevens["onderwerp"] or ""
        if onderwerp and not onderwerp.lower().startswith("re:"):
            onderwerp = f"Re: {onderwerp}"
        communicatie_db.maak_actie(
            db, type="concept-huurder", concept_body=concept,
            concept_onderwerp=onderwerp or None, contact_id=contact_id,
            pand_slug=pand_slug, ontvanger=ontvanger or None,
        )
    return "communicatie"


def _verwerk_mailbox(config: Config, soort: str, gebruiker: str, wachtwoord: str) -> None:
    try:
        imap = mail_inname.verbind(config.steenhub_imap_host, gebruiker, wachtwoord)
    except mail_inname.MailInnameError as exc:
        logger.error("[%s] inloggen mislukt: %s", soort, exc)
        return
    db = communicatie_db.verbind(communicatie_db.pad(config.state_dir))
    tellers: dict[str, int] = {}
    try:
        ongelezen = mail_inname.haal_ongelezen(imap)
        logger.info("[%s] %d ongelezen bericht(en).", soort, len(ongelezen))
        for uid, raw in ongelezen:
            try:
                code = _verwerk_mail(config, db, soort, raw)
            except Exception:  # noqa: BLE001 - één mail mag de rest niet stoppen
                logger.exception("[%s] mail verwerken mislukt (uid %s) - niet als gelezen gemarkeerd.", soort, uid)
                continue
            tellers[code] = tellers.get(code, 0) + 1
            mail_inname.markeer_gelezen(imap, uid)
    finally:
        db.close()
        try:
            imap.logout()
        except Exception:  # noqa: BLE001
            pass
    if tellers:
        logger.info("[%s] verwerkt: %s", soort, ", ".join(f"{k}={v}" for k, v in tellers.items()))


def _draai(config: Config) -> None:
    bakken = [
        ("onderhoud", config.onderhoud_imap_user, config.onderhoud_imap_password),
        ("communicatie", config.communicatie_imap_user, config.communicatie_imap_password),
    ]
    actief = False
    for soort, gebruiker, wachtwoord in bakken:
        if not (gebruiker and wachtwoord):
            logger.info("[%s] overgeslagen: geen inloggegevens ingesteld.", soort)
            continue
        actief = True
        _verwerk_mailbox(config, soort, gebruiker, wachtwoord)
    if not actief:
        logger.info("Geen enkele mailbox geconfigureerd - niets te doen (zet ONDERHOUD_IMAP_* / "
                    "COMMUNICATIE_IMAP_* in de env om dit aan te zetten).")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_dotenv()
    try:
        config = Config.load()
    except ConfigError as exc:
        logger.error("Configuratiefout: %s", exc)
        raise SystemExit(1)

    logger.info("Container gestart - meteen een inname uitvoeren, naast het dagelijkse schema.")
    _draai(config)

    while True:
        wachttijd = _seconden_tot_volgende_run()
        logger.info("Volgende mail-inname over %.1f uur (dagelijks rond %02d:00).",
                    wachttijd / 3600, _UUR_VAN_DE_DAG)
        time.sleep(wachttijd)
        _draai(config)


if __name__ == "__main__":
    main()

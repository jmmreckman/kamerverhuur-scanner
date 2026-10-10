"""Eenmalige backfill van het listings-archief (rotterdam_scanner/archief.py) uit de
mailbox: lees alle Funda- en NVM-alertmails van de afgelopen ~half jaar en voeg elke
daarin genoemde woning toe aan het archief, met de e-maildatum als 'gezien'-datum.

Waarom: het blijvende archief vult pas sinds de invoering ervan. De mailbox bevat nog
~6 maanden alertmails, dus daarmee kunnen we de te-koop-geweest-historie met
terugwerkende kracht (deels) aanvullen. Move.nl valt erbuiten (dat is sinds kort een
scrape, geen mail).

Draaien op de VPS (waar de mailbox-credentials als env staan), in de scanner-container,
bijvoorbeeld:

    docker compose run --rm fundazoeker python -m scripts.backfill_archief_uit_mail
    # optioneel een ander aantal dagen terugkijken:
    docker compose run --rm fundazoeker python -m scripts.backfill_archief_uit_mail 183

Idempotent: het archief wordt samengevoegd (vul_aan), nooit geleegd, dus nog eens
draaien kan geen kwaad.
"""
from __future__ import annotations

import imaplib
import sys
from datetime import date, datetime, timedelta
from email import message_from_bytes
from email.utils import parsedate_to_datetime

from rotterdam_scanner import archief
from rotterdam_scanner.config import load_config
from rotterdam_scanner.funda_mail import FundaListing, _get_body, scan_email_body
from rotterdam_scanner.nvm_mail import _STANDAARD_ONDERWERP, _beste_tekst, parse_nvm_body
from rotterdam_scanner.state import ListingState

STANDAARD_DAGEN = 183  # ~half jaar


def verwerk_sightings(sightings: list[tuple[FundaListing, date]]) -> list[ListingState]:
    """Pure kern: bundel losse waarnemingen (listing + e-maildatum) per object_id tot
    ListingStates met het juiste eerst/laatst-gezien-bereik en de verzamelde bronnen.
    Woningen zonder bruikbaar object_id (geen postcode+huisnummer) worden overgeslagen."""
    per_id: dict[str, dict] = {}
    for listing, gezien in sightings:
        oid = listing.object_id
        if not oid:
            continue
        iso = gezien.isoformat()
        rec = per_id.get(oid)
        if rec is None:
            per_id[oid] = {
                "listing": listing,
                "eerst": iso,
                "laatst": iso,
                "bronnen": {listing.bron},
                "prijs": listing.prijs,
            }
        else:
            rec["eerst"] = min(rec["eerst"], iso)
            rec["laatst"] = max(rec["laatst"], iso)
            rec["bronnen"].add(listing.bron)
            if listing.prijs is not None:
                rec["prijs"] = listing.prijs

    states = []
    for oid, rec in per_id.items():
        l = rec["listing"]
        states.append(ListingState(
            object_id=oid,
            url=l.url,
            weergavenaam=l.weergavenaam,
            eerst_gezien=rec["eerst"],
            laatst_gezien=rec["laatst"],
            status="afgevallen",  # historische waarneming; de te-koop-check kijkt naar de datum
            straatnaam=l.straatnaam,
            huisnummer=(f"{l.huisnummer}{l.toevoeging}" if l.huisnummer else None),
            prijs=rec["prijs"],
            bronnen=sorted(b for b in rec["bronnen"] if b),
        ))
    return states


def _datum_van(msg) -> date | None:
    try:
        dt = parsedate_to_datetime(msg.get("Date"))
        return dt.date() if dt else None
    except (TypeError, ValueError):
        return None


def _verzamel_uit_mailbox(config, dagen: int) -> list[tuple[FundaListing, date]]:
    """IMAP-schil: haal alle Funda- en NVM-mails vanaf `dagen` terug op en parse ze tot
    (listing, e-maildatum)-waarnemingen. Vereist de mailbox-credentials uit de config."""
    sightings: list[tuple[FundaListing, date]] = []
    since = (datetime.now() - timedelta(days=dagen)).strftime("%d-%b-%Y")

    with imaplib.IMAP4_SSL(config.imap_host) as imap:
        imap.login(config.gmail_address, config.gmail_app_password)
        imap.select(config.funda_mail_folder)

        # Funda-alertmails
        _, data = imap.search(None, f'(SINCE "{since}" HEADER FROM "funda")')
        funda_ids = data[0].split() if data and data[0] else []
        for mid in funda_ids:
            _, md = imap.fetch(mid, "(RFC822)")
            if not md or not md[0]:
                continue
            msg = message_from_bytes(md[0][1])
            gezien = _datum_van(msg) or date.today()
            for listing in scan_email_body(_get_body(msg)).listings:
                sightings.append((listing, gezien))

        # NVM / makelaarsmails
        _, data = imap.search(None, f'(SINCE "{since}" SUBJECT "{_STANDAARD_ONDERWERP}")')
        nvm_ids = data[0].split() if data and data[0] else []
        for mid in nvm_ids:
            _, md = imap.fetch(mid, "(RFC822)")
            if not md or not md[0]:
                continue
            msg = message_from_bytes(md[0][1])
            gezien = _datum_van(msg) or date.today()
            listings, _ = parse_nvm_body(_beste_tekst(msg))
            for listing in listings:
                sightings.append((listing, gezien))

    return sightings


def main(argv: list[str]) -> int:
    dagen = int(argv[1]) if len(argv) > 1 else STANDAARD_DAGEN
    config = load_config()

    print(f"Backfill archief uit mail: {dagen} dagen terugkijken...")
    sightings = _verzamel_uit_mailbox(config, dagen)
    print(f"  {len(sightings)} waarnemingen uit de mailbox gelezen.")

    states = verwerk_sightings(sightings)
    print(f"  {len(states)} unieke woningen (met postcode+huisnummer).")

    pad = archief.archief_pad_voor(config.state_path)
    arch = archief.ListingArchief(pad)
    voor = len(arch)
    arch.vul_aan(states)
    arch.save()
    na = len(arch)
    print(f"  Archief: {voor} -> {na} records ({na - voor} nieuw toegevoegd); opgeslagen in {pad}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

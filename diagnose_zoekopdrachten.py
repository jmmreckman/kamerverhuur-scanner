"""Diagnose: welke Funda-zoekopdrachten leveren structureel te veel woningen aan?

Funda toont per zoekopdracht maar ~2 woningen los in de alertmail; de rest zit
achter een "Bekijk alle N woningen"-knop en kan de scanner niet los uitlezen (die
overzichtspagina zit achter een inlogmuur, zie diagnose_bekijk_alle.py). Elke
alert met meer dan ~2 nieuwe woningen laat dus woningen liggen.

Dit script leest de Funda-alertmails van de afgelopen weken, groepeert ze per
zoekopdracht (op onderwerp) en telt per zoekopdracht hoe vaak en hoeveel woningen
er gemist zijn. Wijzigt niets, stuurt geen mail - alleen uitlezen en printen.

Gebruik:  docker compose exec fundazoeker python3 diagnose_zoekopdrachten.py [DAGEN]
          (standaard 21 dagen = 3 weken)
"""
from __future__ import annotations

import email
import imaplib
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from email.header import decode_header

from rotterdam_scanner.config import load_config
from rotterdam_scanner.funda_mail import _BEKIJK_ALLE_RE, _get_body, scan_email_body


def _decode(ruw: str | None) -> str:
    if not ruw:
        return "(geen onderwerp)"
    delen = []
    for tekst, codering in decode_header(ruw):
        if isinstance(tekst, bytes):
            delen.append(tekst.decode(codering or "utf-8", errors="replace"))
        else:
            delen.append(tekst)
    return re.sub(r"\s+", " ", "".join(delen)).strip()


def main() -> None:
    dagen = int(sys.argv[1]) if len(sys.argv) > 1 else 21
    config = load_config()

    with imaplib.IMAP4_SSL(config.imap_host) as imap:
        imap.login(config.gmail_address, config.gmail_app_password)
        imap.select(config.funda_mail_folder)
        since = (datetime.now() - timedelta(days=dagen)).strftime("%d-%b-%Y")
        status, data = imap.search(None, f'(SINCE "{since}" HEADER FROM "funda")')
        if status != "OK":
            print(f"IMAP-zoekopdracht mislukt: {status}")
            return
        message_ids = data[0].split()
        print(f"{len(message_ids)} Funda-mail(s) in de laatste {dagen} dagen.\n")

        # per zoekopdracht (= onderwerp): tellingen
        stat = defaultdict(lambda: {"mails": 0, "overflow": 0, "aangekondigd": 0,
                                    "herkend": 0, "gemist": 0, "max_n": 0})
        overflow_log: list[tuple[str, str, int, int]] = []  # datum, onderwerp, aangekondigd, gemist

        for msg_id in message_ids:
            ok, msg_data = imap.fetch(msg_id, "(RFC822)")
            if ok != "OK" or not msg_data or msg_data[0] is None:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            onderwerp = _decode(msg.get("Subject"))
            datum = (msg.get("Date") or "")[:16]
            body = _get_body(msg)

            herkend = len(scan_email_body(body).listings)
            ns = [int(n) for n in _BEKIJK_ALLE_RE.findall(body)]
            aangekondigd = sum(ns)
            # "gemist" = wat funda aankondigt maar niet los in de mail toont
            gemist = max(0, aangekondigd - herkend) if aangekondigd else 0

            s = stat[onderwerp]
            s["mails"] += 1
            s["aangekondigd"] += aangekondigd
            s["herkend"] += herkend
            s["gemist"] += gemist
            s["max_n"] = max(s["max_n"], max(ns) if ns else 0)
            if gemist > 0:
                s["overflow"] += 1
                overflow_log.append((datum, onderwerp, aangekondigd, gemist))

    # ---- rapport ----
    ranglijst = sorted(stat.items(), key=lambda kv: kv[1]["gemist"], reverse=True)
    print("=" * 96)
    print("PER ZOEKOPDRACHT (meest gemist bovenaan)")
    print("=" * 96)
    print(f"{'gemist':>7} {'overflow':>9} {'mails':>6} {'max/mail':>9}  zoekopdracht (onderwerp)")
    print("-" * 96)
    for onderwerp, s in ranglijst:
        print(f"{s['gemist']:>7} {s['overflow']:>4}/{s['mails']:<4} {s['mails']:>6} {s['max_n']:>9}  {onderwerp[:52]}")

    tot_gemist = sum(s["gemist"] for _, s in ranglijst)
    tot_herkend = sum(s["herkend"] for _, s in ranglijst)
    tot_mails = sum(s["mails"] for _, s in ranglijst)
    print("-" * 96)
    print(f"TOTAAL: {tot_mails} mails, {tot_herkend} woningen wél binnengehaald, "
          f"{tot_gemist} woningen GEMIST achter 'Bekijk alle'.")
    if tot_herkend + tot_gemist:
        pct = 100 * tot_gemist / (tot_herkend + tot_gemist)
        print(f"        → structureel {pct:.0f}% van het aanbod gemist.")

    print("\n" + "=" * 96)
    print(f"OVERFLOW-DAGEN (de {len(overflow_log)} mails waar woningen gemist zijn)")
    print("=" * 96)
    for datum, onderwerp, aangekondigd, gemist in sorted(overflow_log, reverse=True):
        print(f"{datum:>16}  aangekondigd {aangekondigd:>3}, gemist {gemist:>3}  |  {onderwerp[:48]}")

    print("\nAdvies: splits de zoekopdrachten bovenaan de ranglijst in kleinere stukken "
          "(smallere prijs-/m²-band of per postcodegebied), zodat er per alert ≤2 nieuwe "
          "woningen binnenkomen. Zie de begeleidende uitleg.")


if __name__ == "__main__":
    main()

"""Eenmalig opschoon-scriptje voor de Grondherendijk-19-bug: zoekt "actief" woningen
in state.json met een adres zonder toevoeging (object_id zoals "3082DD-19" i.p.v.
"3082DD-19B") waarvan het huisnummer in werkelijkheid uit meerdere eenheden bestaat
(bv. 19A én 19B). Zulke woningen zijn destijds stilzwijgend aan de verkeerde eenheid
gekoppeld (PDOK geeft zonder toevoeging de eerste/standaard-eenheid terug, ook al gaat
de advertentie zelf over een andere eenheid), met foutieve BAG/WOZ/investeringscijfers
tot gevolg. Nieuwe woningen kunnen dit sinds de fix in geocode.py niet meer overkomen
(geocode_by_postcode weigert nu te gokken in zo'n geval) - dit script ruimt alleen de
al bestaande, foutief opgeslagen records op.

Zet gevonden woningen op "afgevallen" (handmatig_verwijderd=True, zodat ze niet vanzelf
terugkomen bij de volgende scan) met een duidelijke afvalreden. Voeg ze daarna zelf
opnieuw toe via "Toevoegen" op de kaart-website, mét de juiste toevoeging (te zien in
de URL/advertentie zelf) - dan worden ze aan de juiste eenheid gekoppeld.

Wijzigt state.json alleen met --uitvoeren; zonder die vlag is het een dry-run die
alleen laat zien wat er zou gebeuren.

Gebruik:
  docker compose exec fundazoeker python3 opschonen_ontbrekende_toevoeging.py             # dry-run
  docker compose exec fundazoeker python3 opschonen_ontbrekende_toevoeging.py --uitvoeren  # daadwerkelijk opschonen
"""
from __future__ import annotations

import argparse
import re
from datetime import date

from rotterdam_scanner.config import load_config
from rotterdam_scanner.geocode import heeft_meerdere_eenheden
from rotterdam_scanner.state import StateStore

_OBJECT_ID_RE = re.compile(r"^(?P<postcode>\d{4}[A-Z]{2})-(?P<huisnummer>\d+)(?P<toevoeging>[A-Za-z0-9]*)$")

_AFVALREDEN = (
    "Automatisch opgeschoond: adres zonder toevoeging opgeslagen op een huisnummer met "
    "meerdere eenheden (bv. A/B/C) - mogelijk aan de verkeerde eenheid gekoppeld, met "
    "foutieve BAG/WOZ/investeringscijfers tot gevolg. Voeg desgewenst opnieuw toe via "
    "'Toevoegen' op de kaart-website, mét de juiste toevoeging."
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--uitvoeren", action="store_true", help="daadwerkelijk wijzigen (standaard: alleen dry-run tonen)"
    )
    args = parser.parse_args()

    config = load_config()
    state = StateStore(config.state_path)

    gevonden = []
    for item in state.all():
        if item.status != "actief":
            continue
        match = _OBJECT_ID_RE.match(item.object_id)
        if not match or match.group("toevoeging"):
            continue  # heeft al een toevoeging in de object_id, dus niet dit probleem

        postcode = match.group("postcode")
        huisnummer = match.group("huisnummer")
        try:
            ambigu = heeft_meerdere_eenheden(postcode, huisnummer)
        except Exception as exc:  # noqa: BLE001 - best-effort diagnose-script
            print(f"Kon {item.object_id} niet checken ({exc}), overgeslagen.")
            continue
        if ambigu:
            gevonden.append(item)

    if not gevonden:
        print("Geen woningen gevonden met dit probleem.")
        return

    print(f"{len(gevonden)} woning(en) gevonden zonder toevoeging op een adres met meerdere eenheden:\n")
    for item in gevonden:
        print(f"- {item.object_id} | {item.weergavenaam} | {item.url}")

    if not args.uitvoeren:
        print("\nDry-run: er is niets gewijzigd. Draai met --uitvoeren om ze op 'afgevallen' te zetten.")
        return

    vandaag_iso = date.today().isoformat()
    for item in gevonden:
        item.status = "afgevallen"
        item.handmatig_verwijderd = True
        item.afvalreden = _AFVALREDEN
        item.laatst_gezien = vandaag_iso
        state.upsert(item)
    state.save()
    print(f"\n{len(gevonden)} woning(en) op 'afgevallen' gezet.")


if __name__ == "__main__":
    main()

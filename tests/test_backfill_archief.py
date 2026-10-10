"""Tests voor de pure kern van de eenmalige mail->archief-backfill
(scripts/backfill_archief_uit_mail.verwerk_sightings)."""
from datetime import date

from rotterdam_scanner.funda_mail import FundaListing
from scripts.backfill_archief_uit_mail import verwerk_sightings


def _listing(postcode, huisnummer, toevoeging="", *, straat="Teststraat", prijs=None, bron="funda"):
    return FundaListing(
        object_id=f"{postcode.replace(' ', '')}-{huisnummer}{toevoeging}" if postcode and huisnummer else None,
        url=f"https://funda.nl/{postcode}-{huisnummer}",
        straatnaam=straat, huisnummer=huisnummer, toevoeging=toevoeging,
        postcode=postcode, woonplaats="Rotterdam", prijs=prijs, bron=bron,
    )


def test_bundelt_waarnemingen_per_object_id():
    a = _listing("3082RT", "42", prijs=300_000)
    sightings = [
        (a, date(2026, 3, 1)),
        (a, date(2026, 6, 15)),   # zelfde woning, later gezien
        (_listing("3082AR", "70", "B"), date(2026, 4, 10)),
    ]
    states = verwerk_sightings(sightings)
    per = {s.object_id: s for s in states}
    assert set(per) == {"3082RT-42", "3082AR-70B"}
    assert per["3082RT-42"].eerst_gezien == "2026-03-01"
    assert per["3082RT-42"].laatst_gezien == "2026-06-15"
    assert per["3082RT-42"].weergavenaam == "Teststraat 42, 3082RT Rotterdam"
    assert per["3082AR-70B"].huisnummer == "70B"


def test_slaat_woningen_zonder_object_id_over():
    zonder = FundaListing(object_id=None, url="https://funda.nl/x", straatnaam=None,
                          huisnummer=None, toevoeging="", postcode=None, woonplaats=None)
    assert verwerk_sightings([(zonder, date(2026, 5, 1))]) == []


def test_verzamelt_bronnen_en_laatste_prijs():
    funda = _listing("3082RT", "42", prijs=300_000, bron="funda")
    nvm = _listing("3082RT", "42", prijs=310_000, bron="nvm")
    states = verwerk_sightings([(funda, date(2026, 3, 1)), (nvm, date(2026, 3, 2))])
    assert states[0].bronnen == ["funda", "nvm"]
    assert states[0].prijs == 310_000  # laatste gezien prijs


def test_states_zijn_te_archiveren(tmp_path):
    from rotterdam_scanner.archief import ListingArchief
    states = verwerk_sightings([(_listing("3082RT", "42"), date(2026, 6, 1))])
    arch = ListingArchief(tmp_path / "arch.json")
    arch.vul_aan(states)
    assert len(arch) == 1
    assert arch.te_koop_geweest_sinds("Teststraat 42, 3082RT Rotterdam", "2026-01-01") is not None

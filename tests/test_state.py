from datetime import date

from rotterdam_scanner.state import ListingState, StateStore


def _listing(object_id="1", eerst="2026-07-01", laatst="2026-07-01", status="actief"):
    return ListingState(
        object_id=object_id,
        url=f"https://www.funda.nl/x/{object_id}/",
        weergavenaam="Teststraat 1, Rotterdam",
        eerst_gezien=eerst,
        laatst_gezien=laatst,
        status=status,
    )


def test_upsert_en_persistentie_over_herstart(tmp_path):
    path = tmp_path / "state.json"
    store = StateStore(path)
    store.upsert(_listing())
    store.save()

    herladen = StateStore(path)
    assert herladen.get("1") is not None
    assert herladen.get("1").status == "actief"


def test_upsert_behoudt_oorspronkelijke_eerst_gezien_datum(tmp_path):
    store = StateStore(tmp_path / "state.json")
    store.upsert(_listing(eerst="2026-07-01", laatst="2026-07-01"))
    store.upsert(_listing(eerst="2026-07-05", laatst="2026-07-05"))

    assert store.get("1").eerst_gezien == "2026-07-01"
    assert store.get("1").laatst_gezien == "2026-07-05"


def test_prune_expired_verwijdert_oude_listings(tmp_path):
    store = StateStore(tmp_path / "state.json")
    store.upsert(_listing(object_id="oud", eerst="2026-01-01", laatst="2026-01-01"))
    store.upsert(_listing(object_id="recent", eerst="2026-07-01", laatst="2026-07-04"))

    store.prune_expired(expiry_days=60, today=date(2026, 7, 5))

    assert store.get("oud") is None
    assert store.get("recent") is not None


def test_dagen_bekend_berekent_verschil_met_eerst_gezien(tmp_path):
    store = StateStore(tmp_path / "state.json")
    store.upsert(_listing(eerst="2026-07-01"))
    assert store.dagen_bekend("1", today=date(2026, 7, 5)) == 4

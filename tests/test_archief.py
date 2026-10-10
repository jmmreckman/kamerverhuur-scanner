"""Tests voor het blijvende listings-archief: toevoegen/bijwerken zonder ooit te
verwijderen, en de te-koop-geweest-match op adres + datumgrens."""
from rotterdam_scanner.archief import (
    ListingArchief,
    archief_pad_voor,
    bouw_te_koop_index,
    normaliseer_adres,
)
from rotterdam_scanner.state import ListingState


def _listing(object_id, weergavenaam, eerst, laatst, status="actief", **kw):
    return ListingState(
        object_id=object_id, url=f"https://funda.nl/{object_id}",
        weergavenaam=weergavenaam, eerst_gezien=eerst, laatst_gezien=laatst,
        status=status, **kw,
    )


def test_normaliseer_adres_vouwt_witruimte_en_hoofdletters():
    assert normaliseer_adres("  Pompstraat 42,  3082RT Rotterdam ") == "pompstraat 42, 3082rt rotterdam"


def test_archief_pad_naast_state():
    p = archief_pad_voor("/data/state.json")
    assert p.name == "listings_archief.json"
    assert str(p.parent) == "/data"


def test_vul_aan_voegt_toe_en_zet_adres_index(tmp_path):
    arch = ListingArchief(tmp_path / "arch.json")
    arch.vul_aan([_listing("1", "Pompstraat 42, Rotterdam", "2026-01-01", "2026-01-10")])
    assert len(arch) == 1
    rec = arch.all()[0]
    assert rec.adres_genormaliseerd == "pompstraat 42, rotterdam"
    assert rec.eerst_gezien == "2026-01-01"
    assert rec.laatst_gezien == "2026-01-10"


def test_vul_aan_werkt_bij_maar_verwijdert_nooit(tmp_path):
    pad = tmp_path / "arch.json"
    arch = ListingArchief(pad)
    # run 1: woning 1 actief
    arch.vul_aan([_listing("1", "Pompstraat 42, Rotterdam", "2026-01-01", "2026-01-05")])
    arch.save()

    # run 2 (nieuw object geladen): woning 1 later weer gezien + woning 2 nieuw
    arch2 = ListingArchief(pad)
    arch2.vul_aan([
        _listing("1", "Pompstraat 42, Rotterdam", "2026-01-01", "2026-02-20"),
        _listing("2", "Doklaan 3, Rotterdam", "2026-02-01", "2026-02-20"),
    ])
    arch2.save()

    # run 3: woning 1 valt in de live-state weg (geprund) -> NIET meer meegegeven.
    arch3 = ListingArchief(pad)
    arch3.vul_aan([_listing("2", "Doklaan 3, Rotterdam", "2026-02-01", "2026-03-01")])
    arch3.save()

    arch_eind = ListingArchief(pad)
    ids = {r.object_id for r in arch_eind.all()}
    assert ids == {"1", "2"}  # woning 1 blijft bewaard ondanks dat hij uit de state verdween
    rec1 = next(r for r in arch_eind.all() if r.object_id == "1")
    assert rec1.eerst_gezien == "2026-01-01"
    assert rec1.laatst_gezien == "2026-02-20"  # ruimste bereik


def test_te_koop_geweest_sinds_respecteert_datumgrens(tmp_path):
    arch = ListingArchief(tmp_path / "arch.json")
    arch.vul_aan([
        _listing("1", "Pompstraat 42, Rotterdam", "2025-01-01", "2026-05-01"),  # recent
        _listing("2", "Oudestraat 9, Rotterdam", "2024-01-01", "2024-06-01"),   # oud
    ])
    grens = "2025-10-09"  # ~12 mnd terug
    assert arch.te_koop_geweest_sinds("Pompstraat 42, Rotterdam", grens) is not None
    assert arch.te_koop_geweest_sinds("Oudestraat 9, Rotterdam", grens) is None
    assert arch.te_koop_geweest_sinds("Bestaatniet 1, Rotterdam", grens) is None


def test_laatst_beschikbaar_wint_als_peildatum(tmp_path):
    arch = ListingArchief(tmp_path / "arch.json")
    # laatst_gezien oud, maar beschikbaarheidscheck zag 'm recenter nog te koop
    arch.vul_aan([_listing("1", "Pompstraat 42, Rotterdam", "2025-01-01", "2025-02-01",
                           laatst_beschikbaar="2026-06-01")])
    rec = arch.all()[0]
    assert rec.laatste_peildatum() == "2026-06-01"
    assert arch.te_koop_geweest_sinds("Pompstraat 42, Rotterdam", "2026-01-01") is not None


def test_bouw_te_koop_index_combineert_state_en_archief(tmp_path):
    # Live state: woning recent gezien. Archief: zelfde adres ouder + een ander adres.
    live = [_listing("1", "Pompstraat 42, Rotterdam", "2026-03-01", "2026-09-20")]
    arch = ListingArchief(tmp_path / "a.json")
    arch.vul_aan([
        _listing("1", "Pompstraat 42, Rotterdam", "2026-01-01", "2026-05-01"),
        _listing("2", "Doklaan 3, Rotterdam", "2026-02-01", "2026-07-15"),
    ])
    idx = bouw_te_koop_index(live, arch.all())
    # Per adres: 'tot' is de meest recente datum (state 2026-09-20 wint van archief
    # 2026-05-01), 'sinds' de vroegste over alle bronnen (archief 2026-01-01).
    assert idx["pompstraat 42, rotterdam"]["tot"] == "2026-09-20"
    assert idx["pompstraat 42, rotterdam"]["sinds"] == "2026-01-01"
    assert idx["doklaan 3, rotterdam"]["tot"] == "2026-07-15"


def test_bouw_te_koop_index_gebruikt_laatst_beschikbaar(tmp_path):
    live = [_listing("1", "Pompstraat 42, Rotterdam", "2026-01-01", "2026-02-01",
                     laatst_beschikbaar="2026-08-01")]
    idx = bouw_te_koop_index(live, [])
    assert idx["pompstraat 42, rotterdam"]["tot"] == "2026-08-01"  # beschikbaar > laatst_gezien


def test_bouw_te_koop_index_leeg():
    assert bouw_te_koop_index([], []) == {}

from datetime import date

from rotterdam_scanner.pipeline import RunResult
from rotterdam_scanner.report import build_html_report, build_text_report
from rotterdam_scanner.state import ListingState


def _listing(object_id, weergavenaam, eerst_gezien, wijknaam="Centrum", prijs=250_000, bag_oppervlakte=60):
    return ListingState(
        object_id=object_id,
        url=f"https://example.com/{object_id}",
        weergavenaam=weergavenaam,
        eerst_gezien=eerst_gezien,
        laatst_gezien="2026-07-09",
        status="actief",
        wijknaam=wijknaam,
        prijs=prijs,
        bag_oppervlakte=bag_oppervlakte,
    )


def test_html_report_toont_alleen_nieuwe_woningen_in_nieuwe_kansen_blok():
    nieuw = _listing("NEW-1", "Nieuwstraat 1, Rotterdam", "2026-07-09")
    oud = _listing("OLD-1", "Oudstraat 2, Rotterdam", "2026-06-20")
    result = RunResult(alle_actief=[nieuw, oud], nieuw_actief=[nieuw])

    html = build_html_report(result, date(2026, 7, 9), "scanner@example.com")

    nieuwe_sectie = html.split("Nieuwe kansen vandaag")[1].split("Openstaande kansen")[0]
    assert "Nieuwstraat 1" in nieuwe_sectie
    assert "Oudstraat 2" not in nieuwe_sectie

    openstaande_sectie = html.split("Openstaande kansen")[1]
    assert "Nieuwstraat 1" in openstaande_sectie
    assert "Oudstraat 2" in openstaande_sectie


def test_html_report_nieuwe_kansen_blok_toont_geen_woningen_bij_leeg():
    oud = _listing("OLD-1", "Oudstraat 2, Rotterdam", "2026-06-20")
    result = RunResult(alle_actief=[oud], nieuw_actief=[])

    html = build_html_report(result, date(2026, 7, 9), "scanner@example.com")

    assert "Nieuwe kansen vandaag (0)" in html
    nieuwe_sectie = html.split("Nieuwe kansen vandaag")[1].split("Openstaande kansen")[0]
    assert "Geen nieuwe kansen vandaag." in nieuwe_sectie


def test_html_report_bevat_geen_zelfbewoningsplicht_melding_meer():
    nieuw = _listing("NEW-1", "Nieuwstraat 1, Rotterdam", "2026-07-09")
    result = RunResult(alle_actief=[nieuw], nieuw_actief=[nieuw])

    html = build_html_report(result, date(2026, 7, 9), "scanner@example.com")

    assert "zelfbewoningsplicht" not in html.lower()


def test_text_report_toont_alleen_nieuwe_woningen_in_nieuwe_kansen_blok():
    nieuw = _listing("NEW-1", "Nieuwstraat 1, Rotterdam", "2026-07-09")
    oud = _listing("OLD-1", "Oudstraat 2, Rotterdam", "2026-06-20")
    result = RunResult(alle_actief=[nieuw, oud], nieuw_actief=[nieuw])

    text = build_text_report(result, date(2026, 7, 9), "scanner@example.com")

    nieuwe_sectie = text.split("Nieuwe kansen vandaag")[1].split("Openstaande kansen")[0]
    assert "Nieuwstraat 1" in nieuwe_sectie
    assert "Oudstraat 2" not in nieuwe_sectie

    openstaande_sectie = text.split("Openstaande kansen")[1]
    assert "Nieuwstraat 1" in openstaande_sectie
    assert "Oudstraat 2" in openstaande_sectie


def test_text_report_bevat_geen_zelfbewoningsplicht_melding_meer():
    nieuw = _listing("NEW-1", "Nieuwstraat 1, Rotterdam", "2026-07-09")
    result = RunResult(alle_actief=[nieuw], nieuw_actief=[nieuw])

    text = build_text_report(result, date(2026, 7, 9), "scanner@example.com")

    assert "zelfbewoningsplicht" not in text.lower()


def test_text_report_zonder_extra_checks_laat_regel_weg():
    zonder_woz = _listing("NEW-1", "Nieuwstraat 1, Rotterdam", "2026-07-09")
    result = RunResult(alle_actief=[zonder_woz], nieuw_actief=[zonder_woz])

    text = build_text_report(result, date(2026, 7, 9), "scanner@example.com")

    assert "nog te checken" not in text

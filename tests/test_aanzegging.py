from datetime import date

from webapp.aanzegging import bereken_aanzeg_status


def test_geen_waarschuwing_bij_onbepaalde_tijd():
    assert bereken_aanzeg_status("onbepaalde tijd") is None
    assert bereken_aanzeg_status(None) is None
    assert bereken_aanzeg_status("") is None


def test_geen_waarschuwing_ruim_voor_het_venster():
    # Einddatum over 6 maanden - nog veel te vroeg om aan te zeggen
    status = bereken_aanzeg_status("31-12-2026", vandaag=date(2026, 6, 1))
    assert status is not None
    assert not status.moet_nu_aanzeggen
    assert not status.venster_verstreken


def test_moet_nu_aanzeggen_binnen_venster():
    # Einddatum 31-07-2026, vandaag 15-06-2026 -> binnen 1-3 maanden voor einde
    status = bereken_aanzeg_status("31-07-2026", vandaag=date(2026, 6, 15))
    assert status.moet_nu_aanzeggen
    assert not status.venster_verstreken


def test_venster_verstreken_als_te_laat():
    # Einddatum 31-07-2026, vandaag 15-07-2026 -> binnen 1 maand voor einde, dus te laat
    status = bereken_aanzeg_status("31-07-2026", vandaag=date(2026, 7, 15))
    assert not status.moet_nu_aanzeggen
    assert status.venster_verstreken


def test_geen_waarschuwing_na_einddatum():
    status = bereken_aanzeg_status("31-07-2026", vandaag=date(2026, 8, 15))
    assert not status.moet_nu_aanzeggen
    assert not status.venster_verstreken

from rotterdam_scanner.zelfbewoning import (
    bevat_zelfbewoningsplicht,
    classificeer_zelfbewoning,
)


def test_detecteert_zelfbewoningsplicht():
    assert bevat_zelfbewoningsplicht("Let op: voor deze woning geldt een zelfbewoningsplicht.")


def test_detecteert_variant_met_spatie():
    assert bevat_zelfbewoningsplicht("Er geldt een zelf bewoningsplicht voor de koper.")


def test_detecteert_eigen_bewoning_verplicht():
    assert bevat_zelfbewoningsplicht("Eigen bewoning verplicht per direct na levering.")


def test_geen_valse_positief_bij_normale_tekst():
    assert not bevat_zelfbewoningsplicht("Ruime eengezinswoning met tuin op het zuiden.")


def test_lege_tekst():
    assert not bevat_zelfbewoningsplicht("")
    assert not bevat_zelfbewoningsplicht(None)


# --- uitgebreide classificatie: plicht vs. niet-clausule vs. anti-speculatie ---

def test_niet_zelfbewoningsclausule_is_geen_plicht():
    r = classificeer_zelfbewoning("Een niet-zelfbewoningsclausule van toepassing.")
    assert r["zelfbewoningsplicht"] is False
    assert r["niet_zelfbewoningsclausule"] is True


def test_geen_zelfbewoningsplicht_telt_niet_als_plicht():
    assert classificeer_zelfbewoning("Er geldt geen zelfbewoningsplicht.")["zelfbewoningsplicht"] is False


def test_plicht_wordt_wel_gedetecteerd():
    r = classificeer_zelfbewoning("Er geldt een zelfbewoningsplicht voor de koper.")
    assert r["zelfbewoningsplicht"] is True
    assert r["niet_zelfbewoningsclausule"] is False


def test_anti_speculatie_en_kettingbeding():
    assert classificeer_zelfbewoning("Met een anti-speculatiebeding.")["anti_speculatie"] is True
    assert classificeer_zelfbewoning("Een kettingbeding is van toepassing.")["anti_speculatie"] is True


def test_bevat_blijft_backward_compatibel():
    # De niet-clausule mag de oude helper niet laten afgaan.
    assert bevat_zelfbewoningsplicht("niet-zelfbewoningsclausule van toepassing") is False

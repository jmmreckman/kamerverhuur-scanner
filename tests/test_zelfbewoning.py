from rotterdam_scanner.zelfbewoning import bevat_zelfbewoningsplicht


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

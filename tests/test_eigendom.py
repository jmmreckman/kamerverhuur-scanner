from rotterdam_scanner.eigendom import (
    EIGEN_GROND,
    ERFPACHT,
    ERFPACHT_AFGEKOCHT,
    ONBEKEND,
    classificeer_eigendom,
)


def test_volle_eigendom_veld():
    assert classificeer_eigendom("Volle eigendom")["soort"] == EIGEN_GROND


def test_erfpacht_veld():
    r = classificeer_eigendom("Erfpacht")
    assert r["soort"] == ERFPACHT and not r["afgekocht"]


def test_erfpacht_afgekocht_uit_tekst():
    r = classificeer_eigendom("Erfpacht", "De erfpacht is eeuwigdurend afgekocht.")
    assert r["soort"] == ERFPACHT_AFGEKOCHT and r["afgekocht"]


def test_veld_leeg_valt_terug_op_tekst_eigen_grond():
    assert classificeer_eigendom(None, "De woning is gelegen op eigen grond.")["soort"] == EIGEN_GROND


def test_veld_leeg_valt_terug_op_tekst_erfpacht_met_canon():
    r = classificeer_eigendom("", "Erfpacht met een canon van € 500 per jaar.")
    assert r["soort"] == ERFPACHT and r["canon_genoemd"]


def test_onbekend_zonder_signaal():
    assert classificeer_eigendom(None, "Mooie woning met tuin op het zuiden.")["soort"] == ONBEKEND


def test_gestructureerd_veld_is_leidend_boven_tekst():
    # Veld zegt eigen grond; het woord 'erfpacht' in de tekst mag dat niet omdraaien.
    r = classificeer_eigendom("Volle eigendom", "In de buurt staan veel woningen op erfpacht.")
    assert r["soort"] == EIGEN_GROND

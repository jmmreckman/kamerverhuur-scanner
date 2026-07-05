from rotterdam_scanner.opkoop import check_opkoopbescherming


def test_wijk_niet_in_lijst_valt_nooit_af_op_opkoopbescherming():
    result = check_opkoopbescherming("Rotterdam Centrum", 470_000)
    assert result.in_beschermde_wijk is False
    assert result.valt_af is False
    assert result.woz_check_nodig is False


def test_wijk_in_lijst_vereist_handmatige_woz_check():
    result = check_opkoopbescherming("Middelland", 470_000)
    assert result.in_beschermde_wijk is True
    assert result.valt_af is None
    assert result.woz_check_nodig is True
    assert result.woz_check_url == "https://www.wozwaardeloket.nl/"


def test_wijknaam_is_hoofdletterongevoelig():
    result = check_opkoopbescherming("mIDDELLAND", 470_000)
    assert result.in_beschermde_wijk is True


def test_grens_wordt_correct_getoond_met_duizendtal_punt():
    result = check_opkoopbescherming("Bloemhof", 470_000)
    assert "€470.000" in result.toelichting
    assert ". anders" not in result.toelichting

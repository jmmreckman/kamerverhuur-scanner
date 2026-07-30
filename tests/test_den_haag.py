from rotterdam_scanner import den_haag


def test_is_den_haag_herkent_woonplaatsvarianten():
    assert den_haag.is_den_haag("'s-Gravenhage") is True
    assert den_haag.is_den_haag("Den Haag") is True
    assert den_haag.is_den_haag("Rotterdam") is False


def test_wijk_toegestaan_voor_groene_wijk():
    assert den_haag.wijk_toegestaan("Benoordenhout") is True
    assert den_haag.wijk_toegestaan("Regentessekwartier") is True


def test_wijk_niet_toegestaan_voor_zwakke_wijk():
    # Schildersbuurt/Moerwijk scoren onder 'goed' -> geen vergunning.
    assert den_haag.wijk_toegestaan("Schildersbuurt") is False
    assert den_haag.wijk_toegestaan("Moerwijk") is False
    # Loosduinen bleef 'ruim voldoende' (net onder de grens) -> ook niet.
    assert den_haag.wijk_toegestaan("Loosduinen") is False


def test_wijk_toegestaan_negeert_koppeltekens_en_spaties():
    # PDOK kan een andere schrijfwijze teruggeven dan de officiële lijst.
    assert den_haag.wijk_toegestaan("Bomen en Bloemenbuurt") is True  # zonder koppelteken
    assert den_haag.wijk_toegestaan("geuzen-  en   statenkwartier") is True


def test_wijk_toegestaan_strip_pdok_wijk_prefix():
    # PDOK geeft de Haagse wijknaam als "Wijk NN <naam>" terug; de buurtnaam is vaak
    # een deelgebied dat niet op de lijst staat. Zonder het strippen van die prefix
    # vielen die woningen onterecht af (echt gemeld: 68 van 92 "afgevallen").
    assert den_haag.wijk_toegestaan("Wijk 04 Benoordenhout", "Uilennest") is True
    assert den_haag.wijk_toegestaan("Wijk 12 Bomen- en Bloemenbuurt", "Bloemenbuurt-Oost") is True
    assert den_haag.wijk_toegestaan("Wijk 40 Wateringse Veld", "Hoge Veld") is True
    # Een zwakke wijk blijft ook mét prefix terecht afvallen.
    assert den_haag.wijk_toegestaan("Wijk 36 Moerwijk", "Moerwijk-Oost") is False


def test_wijk_toegestaan_matcht_op_wijk_of_buurt_niveau():
    assert den_haag.wijk_toegestaan("onbekende buurt", "Benoordenhout") is True
    assert den_haag.wijk_toegestaan("onbekende buurt", "andere buurt") is False


def test_bereken_max_bewoners():
    assert den_haag.bereken_max_bewoners(108) == 6  # 108 // 18
    assert den_haag.bereken_max_bewoners(203) == 8  # 11 -> gecapt op 8
    assert den_haag.bereken_max_bewoners(89) == 4
    assert den_haag.bereken_max_bewoners(None) is None
    assert den_haag.bereken_max_bewoners(0) is None


def test_beoordeel_valt_af_bij_niet_toegestane_wijk():
    res = den_haag.beoordeel("Moerwijk", "", 200, min_bewoners=6)
    assert res.valt_af is True
    assert res.wijk_toegestaan is False
    assert "Leefbaarometer" in res.afvalreden


def test_beoordeel_valt_af_bij_te_weinig_capaciteit():
    # Toegestane wijk, maar te klein: 90 // 18 = 5 < 6 gewenst.
    res = den_haag.beoordeel("Benoordenhout", "", 90, min_bewoners=6)
    assert res.valt_af is True
    assert res.wijk_toegestaan is True
    assert res.max_bewoners == 5
    assert "capaciteit" in res.afvalreden.lower()


def test_beoordeel_geschikte_woning_valt_niet_af_en_geeft_signalen():
    res = den_haag.beoordeel("Benoordenhout", "", 218, min_bewoners=6)
    assert res.valt_af is False
    assert res.wijk_toegestaan is True
    assert res.max_bewoners == 8
    # Informatieve punten aanwezig (geluidsisolatie/brandveiligheid vanaf 5).
    assert any("geluidsisolatie" in s for s in res.signalen)
    assert any("brandveiligheid" in s for s in res.signalen)
    assert any("Wijk-quotum" in s for s in res.signalen)
    assert any("Opkoopbescherming" in s for s in res.signalen)


def test_beoordeel_pand_quotum_toont_aantal_woningen_indien_bekend():
    res = den_haag.beoordeel("Benoordenhout", "", 218, min_bewoners=6, aantal_woningen_in_pand=3)
    assert any("pand heeft 3 woning" in s for s in res.signalen)


def test_beoordeel_zonder_oppervlakte_valt_niet_af_maar_meldt_het():
    res = den_haag.beoordeel("Benoordenhout", "", None, min_bewoners=6)
    assert res.valt_af is False
    assert res.max_bewoners is None
    assert any("Oppervlakte onbekend" in s for s in res.signalen)

from datetime import date
from unittest.mock import patch

from rotterdam_scanner import browser_scraper


def test_lijkt_op_antibot_pagina_herkent_bekende_tekst():
    assert browser_scraper._lijkt_op_antibot_pagina("Je bent bijna op de pagina die je zoekt") is True
    assert browser_scraper._lijkt_op_antibot_pagina("Tulpenstraat 3\n3181 WX Rozenburg (ZH)") is False


def test_haal_listings_op_geeft_waarschuwing_bij_antibot_pagina():
    with patch.object(browser_scraper, "_haal_paginatekst_op", return_value="Je bent bijna op de pagina die je zoekt"):
        listings, fouten = browser_scraper.haal_listings_op("https://www.funda.nl/zoeken/koop?a=1")
    assert listings == []
    assert len(fouten) == 1
    assert "anti-bot-controle" in fouten[0]


def test_haal_listings_op_parseert_echte_pagina_tekst():
    tekst = "Hillevliet 47-A\n3073 KJ Rotterdam\n€ 260.000 k.k.\n97 m²\n3\nE\n"
    with patch.object(browser_scraper, "_haal_paginatekst_op", return_value=tekst):
        listings, fouten = browser_scraper.haal_listings_op("https://www.funda.nl/zoeken/koop?a=1", date(2026, 7, 28))
    assert fouten == []
    assert len(listings) == 1
    assert listings[0].object_id == "3073KJ-47A"
    assert listings[0].prijs == 260000


def test_haal_listings_op_geeft_fout_bij_mislukte_paginaophaling():
    with patch.object(browser_scraper, "_haal_paginatekst_op", side_effect=RuntimeError("timeout")):
        listings, fouten = browser_scraper.haal_listings_op("https://www.funda.nl/zoeken/koop?a=1")
    assert listings == []
    assert len(fouten) == 1
    assert "timeout" in fouten[0]

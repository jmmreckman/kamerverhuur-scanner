from datetime import date
from unittest.mock import MagicMock, patch

from rotterdam_scanner import browser_scraper
from rotterdam_scanner.config import Config


def _config(**overrides):
    defaults = dict(
        gmail_address="scanner@example.com", gmail_app_password="x", report_to=["x@example.com"],
        funda_mail_folder="INBOX", listing_expiry_days=30, opkoopbescherming_woz_grens=470_000,
    )
    defaults.update(overrides)
    return Config(**defaults)


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


def test_inloggen_indien_geconfigureerd_doet_niets_zonder_credentials():
    page = MagicMock()
    browser_scraper._inloggen_indien_geconfigureerd(page, _config())
    page.goto.assert_not_called()


def test_inloggen_indien_geconfigureerd_doet_niets_zonder_config():
    page = MagicMock()
    browser_scraper._inloggen_indien_geconfigureerd(page, None)
    page.goto.assert_not_called()


def test_inloggen_indien_geconfigureerd_navigeert_naar_inlogpagina_met_credentials():
    page = MagicMock()
    config = _config(funda_email="ik@example.com", funda_wachtwoord="geheim")
    browser_scraper._inloggen_indien_geconfigureerd(page, config)
    page.goto.assert_called_once()
    assert page.goto.call_args[0][0] == browser_scraper._FUNDA_INLOGPAGINA
    page.locator.return_value.first.fill.assert_any_call("ik@example.com", timeout=5000)
    page.locator.return_value.first.fill.assert_any_call("geheim", timeout=5000)


def test_inloggen_indien_geconfigureerd_geeft_nooit_een_fout_door():
    # Zonder live toegang tot de inlogpagina kan dit niet 100% geverifieerd worden -
    # een mislukte poging (bv. andere veldnamen dan verwacht) mag nooit de rest van
    # de scan laten stranden.
    page = MagicMock()
    page.goto.side_effect = RuntimeError("pagina niet bereikbaar")
    config = _config(funda_email="ik@example.com", funda_wachtwoord="geheim")
    browser_scraper._inloggen_indien_geconfigureerd(page, config)  # mag niet raisen


def test_accepteer_cookies_indien_aanwezig_klikt_eerste_werkende_knop():
    page = MagicMock()
    page.get_by_role.return_value.click.side_effect = [Exception("niet gevonden"), None]
    browser_scraper._accepteer_cookies_indien_aanwezig(page)
    assert page.get_by_role.call_count == 2


def test_accepteer_cookies_indien_aanwezig_geeft_nooit_een_fout_door():
    page = MagicMock()
    page.get_by_role.return_value.click.side_effect = Exception("nooit gevonden")
    browser_scraper._accepteer_cookies_indien_aanwezig(page)  # mag niet raisen


def test_maak_debug_snapshot_doet_niets_zonder_config():
    page = MagicMock()
    browser_scraper._maak_debug_snapshot(page, None, "test")
    page.screenshot.assert_not_called()


def test_maak_debug_snapshot_schrijft_screenshot_en_html(tmp_path):
    page = MagicMock()
    page.content.return_value = "<html>hallo</html>"
    config = _config(state_path=tmp_path / "state.json")
    browser_scraper._maak_debug_snapshot(page, config, "test")

    debug_map = tmp_path / "browser_debug"
    assert (debug_map / "test.html").read_text(encoding="utf-8") == "<html>hallo</html>"
    page.screenshot.assert_called_once_with(path=str(debug_map / "test.png"), full_page=True)


def test_maak_debug_snapshot_geeft_nooit_een_fout_door(tmp_path):
    page = MagicMock()
    page.screenshot.side_effect = RuntimeError("schijf vol")
    config = _config(state_path=tmp_path / "state.json")
    browser_scraper._maak_debug_snapshot(page, config, "test")  # mag niet raisen


def test_debug_bestanden_zonder_config_geeft_lege_lijst():
    assert browser_scraper.debug_bestanden(None) == []


def test_debug_bestanden_zonder_map_geeft_lege_lijst(tmp_path):
    config = _config(state_path=tmp_path / "state.json")
    assert browser_scraper.debug_bestanden(config) == []


def test_debug_bestanden_geeft_gesorteerde_lijst(tmp_path):
    config = _config(state_path=tmp_path / "state.json")
    page = MagicMock()
    page.content.return_value = "<html></html>"
    browser_scraper._maak_debug_snapshot(page, config, "zoekresultaten")
    browser_scraper._maak_debug_snapshot(page, config, "homepage")
    assert browser_scraper.debug_bestanden(config) == ["homepage.html", "zoekresultaten.html"]


def test_debug_bestand_pad_geeft_none_zonder_config():
    assert browser_scraper.debug_bestand_pad(None, "homepage.png") is None


def test_debug_bestand_pad_geeft_none_voor_onbekend_bestand(tmp_path):
    config = _config(state_path=tmp_path / "state.json")
    assert browser_scraper.debug_bestand_pad(config, "onbekend.png") is None


def test_debug_bestand_pad_geeft_pad_voor_bestaand_bestand(tmp_path):
    config = _config(state_path=tmp_path / "state.json")
    page = MagicMock()
    page.content.return_value = "<html>hallo</html>"
    browser_scraper._maak_debug_snapshot(page, config, "homepage")
    pad = browser_scraper.debug_bestand_pad(config, "homepage.html")
    assert pad is not None
    assert pad.read_text(encoding="utf-8") == "<html>hallo</html>"


def test_debug_bestand_pad_blokkeert_padtraversal(tmp_path):
    config = _config(state_path=tmp_path / "state.json")
    (tmp_path / "geheim.txt").write_text("shh", encoding="utf-8")
    assert browser_scraper.debug_bestand_pad(config, "../geheim.txt") is None

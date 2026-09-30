"""Tests voor de per-account mailvoorkeuren (rotterdam_scanner/mail_voorkeuren.py)."""
import pytest

from rotterdam_scanner import mail_voorkeuren as mv
from rotterdam_scanner.config import Config


def _config(tmp_path, report_to=("fallback@example.com",)):
    return Config(
        gmail_address="s@e.com", gmail_app_password="x", report_to=list(report_to),
        funda_mail_folder="INBOX", listing_expiry_days=30, opkoopbescherming_woz_grens=470_000,
        state_path=tmp_path / "state.json",
    )


def test_geldig_email():
    assert mv.geldig_email("a@b.nl")
    assert not mv.geldig_email("geen-email")
    assert not mv.geldig_email("")


def test_ontvangers_valt_terug_op_report_to_zolang_niets_ingesteld(tmp_path):
    cfg = _config(tmp_path, report_to=["a@x.nl", "b@x.nl"])
    assert mv.ontvangers_voor(cfg, "dagelijkse_kansen") == ["a@x.nl", "b@x.nl"]


def test_zet_en_ontvangers_per_mailing(tmp_path):
    cfg = _config(tmp_path)
    mv.zet_voorkeuren(cfg, "jurian", "jur@x.nl", {"dagelijkse_kansen", "rente_updates"})
    mv.zet_voorkeuren(cfg, "justin", "jus@x.nl", {"dagelijkse_kansen"})  # geen rente
    assert mv.ontvangers_voor(cfg, "dagelijkse_kansen") == ["jur@x.nl", "jus@x.nl"]
    assert mv.ontvangers_voor(cfg, "rente_updates") == ["jur@x.nl"]


def test_ingesteld_account_schakelt_fallback_uit(tmp_path):
    # Zodra één account is ingesteld, telt de env-terugval niet meer.
    cfg = _config(tmp_path, report_to=["oud@x.nl"])
    mv.zet_voorkeuren(cfg, "jurian", "jur@x.nl", {"dagelijkse_kansen"})
    assert mv.ontvangers_voor(cfg, "dagelijkse_kansen") == ["jur@x.nl"]
    assert "oud@x.nl" not in mv.ontvangers_voor(cfg, "dagelijkse_kansen")


def test_leeg_of_ongeldig_mailadres_ontvangt_niet(tmp_path):
    cfg = _config(tmp_path)
    mv.zet_voorkeuren(cfg, "jurian", "", {"dagelijkse_kansen"})
    mv.zet_voorkeuren(cfg, "justin", "geen-email", {"dagelijkse_kansen"})
    assert mv.ontvangers_voor(cfg, "dagelijkse_kansen") == []


def test_alles_uit_stuurt_naar_niemand_geen_fallback(tmp_path):
    cfg = _config(tmp_path, report_to=["oud@x.nl"])
    mv.zet_voorkeuren(cfg, "jurian", "jur@x.nl", set())  # alles uit
    assert mv.ontvangers_voor(cfg, "dagelijkse_kansen") == []
    assert mv.ontvangers_voor(cfg, "rente_updates") == []


def test_voorkeuren_voor_geeft_standaarden_zonder_entry(tmp_path):
    huidig = mv.voorkeuren_voor(_config(tmp_path), "nieuw")
    assert huidig["email"] == ""
    assert all(huidig[k] for k in mv.MAILING_KEYS)  # standaard alles aan


def test_meerdere_adressen_per_account(tmp_path):
    cfg = _config(tmp_path)
    mv.zet_voorkeuren(cfg, "jurian", "a@x.nl, b@y.nl", {"dagelijkse_kansen"})
    assert mv.ontvangers_voor(cfg, "dagelijkse_kansen") == ["a@x.nl", "b@y.nl"]


def test_meerdere_adressen_puntkomma_en_spaties(tmp_path):
    cfg = _config(tmp_path)
    mv.zet_voorkeuren(cfg, "jurian", " a@x.nl ;  b@y.nl ", {"rente_updates"})
    assert mv.ontvangers_voor(cfg, "rente_updates") == ["a@x.nl", "b@y.nl"]


def test_emails_geldig_accepteert_lijst_en_wijst_fout_af():
    assert mv.emails_geldig("a@x.nl, b@y.nl")
    assert mv.emails_geldig("")  # leeg mag
    assert not mv.emails_geldig("a@x.nl, kapot")


def test_ongeldig_adres_in_lijst_valt_weg_maar_geldige_blijven(tmp_path):
    # Via de module (de route weigert de hele invoer al bij een ongeldig adres);
    # ontvangers_voor negeert alsnog een eventueel ongeldig deel.
    cfg = _config(tmp_path)
    mv.zet_voorkeuren(cfg, "jurian", "a@x.nl, kapot", {"dagelijkse_kansen"})
    assert mv.ontvangers_voor(cfg, "dagelijkse_kansen") == ["a@x.nl"]

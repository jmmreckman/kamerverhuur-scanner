"""Tests voor de Move.nl-login met e-mailcode (OTP) + sessie-persistentie.

Pure delen - formulier parsen, code uit de mail halen, tokenopslag en de ververs-/
verse-login-orkestratie - getest met fakes, zonder netwerk of echte mailbox."""
from types import SimpleNamespace

from rotterdam_scanner import move_scrape

LOGIN_HTML = """
<form id="kc-form-login" action="https://move.nl/auth/realms/move/login-actions/authenticate?session_code=ABC&amp;execution=exec1&amp;client_id=move-client&amp;tab_id=T1" method="post">
  <input tabindex="1" name="username" type="email" autofocus/>
  <input tabindex="2" name="password" type="password"/>
  <input id="rememberMe" name="rememberMe" type="checkbox"/>
  <input name="credentialId" type="hidden" value=""/>
  <input class="btn" name="login" type="submit" value="Inloggen"/>
</form>
"""

OTP_HTML = """
<div>Controleer je e-mail</div>
<form id="kc-otp" action="https://move.nl/auth/realms/move/login-actions/authenticate?session_code=XYZ&amp;execution=otpexec&amp;client_id=move-client&amp;tab_id=T2" method="post">
  <input id="otp" name="otp" type="text" placeholder="Verificatiecode uit e-mail" value="" autocomplete="off"/>
  <input name="login" type="submit" value="LOGIN"/>
</form>
"""


def _config(tmp_path):
    return SimpleNamespace(state_path=tmp_path / "data" / "state.json")


def test_parse_login_form_actie_unescaped_en_velden():
    actie, velden = move_scrape._parse_login_form(LOGIN_HTML)
    assert actie.startswith("https://move.nl/auth/realms/move/login-actions/authenticate?")
    assert "&amp;" not in actie and "execution=exec1" in actie
    assert velden["username"][1] == "email"
    assert velden["credentialId"][1] == "hidden"
    assert move_scrape._heeft_wachtwoordveld(velden)


def test_parse_otp_form_en_veldkeuze():
    actie, velden = move_scrape._parse_login_form(OTP_HTML)
    assert "otpexec" in actie
    assert not move_scrape._heeft_wachtwoordveld(velden)
    assert move_scrape._kies_otp_veld(velden) == "otp"


def test_kies_otp_veld_slaat_vaste_velden_over():
    velden = {
        "rememberMe": ("", "checkbox"),
        "credentialId": ("", "hidden"),
        "code": ("", "text"),
    }
    assert move_scrape._kies_otp_veld(velden) == "code"


def test_extract_otp_code_mixed_pj9u68():
    # Zoals de echte Move-mail (text/plain): letters en cijfers door elkaar.
    body = "Vul deze eenmalige code in op het inlogscherm.\r\n\r\nPJ9U68\r\n\r\nDe code is 10 minuten geldig."
    assert move_scrape._extract_otp_code(body) == "PJ9U68"


def test_extract_otp_code_letters_dan_cijfers():
    body = "Vul deze eenmalige code in op het inlogscherm.\n\nNMM424\n\nDe code is 10 minuten geldig."
    assert move_scrape._extract_otp_code(body) == "NMM424"


def test_extract_otp_code_negeert_hexkleur_en_los_getal():
    # De bug: de grijstint #404040 uit de HTML-styling werd als code gepakt.
    html = (
        '<html><head><style>.x{color:#404040}</style></head>'
        '<body style="color:#404040"><p>Vul deze eenmalige code in.</p>'
        '<h1>PJ9U68</h1><span>De code is 10 minuten geldig.</span></body></html>'
    )
    assert move_scrape._extract_otp_code(html) == "PJ9U68"


def test_extract_otp_code_geen():
    assert move_scrape._extract_otp_code("Er staat hier geen code in.") is None


def test_mail_tekst_prefereert_platte_tekst():
    import email.message

    msg = email.message.EmailMessage()
    msg["Subject"] = "Je eenmalige inlogcode voor Move.nl"
    msg.set_content("Vul deze eenmalige code in op het inlogscherm.\n\nPJ9U68\n\nDe code is 10 minuten geldig.")
    msg.add_alternative(
        '<html><body style="color:#404040">Inlogcode <b>PJ9U68</b> 10 minuten</body></html>',
        subtype="html",
    )
    tekst = move_scrape._mail_tekst(msg)
    assert "PJ9U68" in tekst
    assert move_scrape._extract_otp_code(tekst) == "PJ9U68"


def test_token_opslag_roundtrip(tmp_path):
    pad = tmp_path / "move_token.json"
    move_scrape._bewaar_token(pad, {"access_token": "AT", "refresh_token": "RT", "expires_in": 300})
    geladen = move_scrape._laad_opgeslagen_token(pad)
    assert geladen["access_token"] == "AT"
    assert geladen["refresh_token"] == "RT"
    assert "obtained_at" in geladen


def test_laad_ontbrekend_token_is_leeg(tmp_path):
    assert move_scrape._laad_opgeslagen_token(tmp_path / "bestaat_niet.json") == {}


def test_verkrijg_token_ververst_bewaarde_sessie(tmp_path, monkeypatch):
    config = _config(tmp_path)
    move_scrape._bewaar_token(move_scrape._token_pad(config), {"refresh_token": "OUD"})
    monkeypatch.setattr(
        move_scrape,
        "_ververs_token",
        lambda s, rt: {"access_token": "NIEUW_AT", "refresh_token": "NIEUW_RT"} if rt == "OUD" else None,
    )

    def _verbieden(*a, **k):
        raise AssertionError("mocht geen verse login doen")

    monkeypatch.setattr(move_scrape, "_voer_oidc_flow", _verbieden)

    at = move_scrape._verkrijg_access_token(object(), config)
    assert at == "NIEUW_AT"
    assert move_scrape._laad_opgeslagen_token(move_scrape._token_pad(config))["refresh_token"] == "NIEUW_RT"


def test_verkrijg_token_valt_terug_op_verse_login(tmp_path, monkeypatch):
    config = _config(tmp_path)
    move_scrape._bewaar_token(move_scrape._token_pad(config), {"refresh_token": "DOOD"})
    monkeypatch.setattr(move_scrape, "_ververs_token", lambda s, rt: None)
    monkeypatch.setattr(
        move_scrape,
        "_voer_oidc_flow",
        lambda s, c: {"access_token": "VERS_AT", "refresh_token": "VERS_RT"},
    )
    at = move_scrape._verkrijg_access_token(object(), config)
    assert at == "VERS_AT"
    assert move_scrape._laad_opgeslagen_token(move_scrape._token_pad(config))["refresh_token"] == "VERS_RT"


def test_verkrijg_token_behoudt_oud_refresh_als_niet_geroteerd(tmp_path, monkeypatch):
    config = _config(tmp_path)
    move_scrape._bewaar_token(move_scrape._token_pad(config), {"refresh_token": "BLIJF"})
    # Keycloak die het refresh-token niet roteert: alleen een nieuw access_token terug.
    monkeypatch.setattr(move_scrape, "_ververs_token", lambda s, rt: {"access_token": "AT2"})
    at = move_scrape._verkrijg_access_token(object(), config)
    assert at == "AT2"
    assert move_scrape._laad_opgeslagen_token(move_scrape._token_pad(config))["refresh_token"] == "BLIJF"


def test_geen_verse_login_zonder_bewaard_token_gebeurt_via_flow(tmp_path, monkeypatch):
    config = _config(tmp_path)  # geen bewaarde token
    monkeypatch.setattr(
        move_scrape, "_voer_oidc_flow", lambda s, c: {"access_token": "EERSTE_AT", "refresh_token": "EERSTE_RT"}
    )
    at = move_scrape._verkrijg_access_token(object(), config)
    assert at == "EERSTE_AT"


def _dossier_id(kern: str, hash_: str) -> str:
    import base64

    return base64.b64encode(f"SearcherDossier:{kern}|{hash_}".encode()).decode()


def test_stabiele_sleutel_negeert_roterende_hash():
    oud = _dossier_id("25660341|905866|5689083", "061a74be")
    nieuw = _dossier_id("25660341|905866|5689083", "3f64a900")
    assert move_scrape._stabiele_sleutel(oud) == "25660341|905866|5689083"
    assert move_scrape._stabiele_sleutel(oud) == move_scrape._stabiele_sleutel(nieuw)


def test_kies_dossier_id_enkel_dossier():
    assert move_scrape._kies_dossier_id(["ABC"], "") == "ABC"
    assert move_scrape._kies_dossier_id(["ABC"], "iets-anders") == "ABC"


def test_kies_dossier_id_leeg_valt_terug_op_config():
    assert move_scrape._kies_dossier_id([], "CONFIG") == "CONFIG"
    assert move_scrape._kies_dossier_id([], "") is None


def test_kies_dossier_id_meerdere_matcht_op_kern():
    a = _dossier_id("111|222|333", "HASHA")
    b = _dossier_id("999|888|777", "HASHB")
    config_oud = _dossier_id("999|888|777", "OUDEHASH")
    assert move_scrape._kies_dossier_id([a, b], config_oud) == b
    # geen bruikbare config -> eerste
    assert move_scrape._kies_dossier_id([a, b], "") == a

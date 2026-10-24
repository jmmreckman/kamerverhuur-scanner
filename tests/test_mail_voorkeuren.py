import json

from kamerverhuur_scanner.mail_voorkeuren import (
    NOTIFICATIE_TYPES,
    heeft_toegang,
    laad_users,
    ontvangers,
    wil_ontvangen,
)


def test_wil_ontvangen_standaard_true():
    assert wil_ontvangen({}, "huishouden") is True


def test_wil_ontvangen_expliciet_uitgevinkt():
    gebruiker = {"mail_voorkeuren": {"huishouden": False}}
    assert wil_ontvangen(gebruiker, "huishouden") is False
    assert wil_ontvangen(gebruiker, "herinneringen") is True  # andere types blijven aan


def test_heeft_toegang_alle_panden():
    assert heeft_toegang({"alle_panden": True}, "mahoniestraat") is True
    assert heeft_toegang({"alle_panden": True}, "willekeurig-pand") is True


def test_heeft_toegang_specifiek_pand():
    gebruiker = {"alle_panden": False, "panden": ["mahoniestraat"]}
    assert heeft_toegang(gebruiker, "mahoniestraat") is True
    assert heeft_toegang(gebruiker, "baumannlaan") is False


def test_ontvangers_filtert_afgemeld_adres_uit_basis():
    users = {
        "jurian": {"email": "jurian@example.com", "alle_panden": True, "mail_voorkeuren": {"huishouden": False}},
    }
    resultaat = ontvangers(users, "mahoniestraat", "huishouden", ["jurian@example.com", "extern@example.com"])
    assert resultaat == ["extern@example.com"]  # extern@ heeft geen account, blijft gewoon staan


def test_ontvangers_voegt_nog_niet_aanwezig_adres_toe():
    users = {
        "jurian": {"email": "jurian@example.com", "alle_panden": True},
    }
    resultaat = ontvangers(users, "mahoniestraat", "huishouden", [])
    assert resultaat == ["jurian@example.com"]


def test_ontvangers_zonder_toegang_tot_pand_wordt_niet_toegevoegd():
    users = {
        "justin": {"email": "justin@example.com", "alle_panden": False, "panden": ["mahoniestraat"]},
    }
    resultaat = ontvangers(users, "baumannlaan", "huishouden", [])
    assert resultaat == []


def test_ontvangers_gebruiker_zonder_email_heeft_geen_effect():
    users = {"jurian": {"alle_panden": True, "mail_voorkeuren": {"huishouden": False}}}
    resultaat = ontvangers(users, "mahoniestraat", "huishouden", ["jurian@example.com"])
    assert resultaat == ["jurian@example.com"]  # geen e-mailadres bij het account = geen effect


def test_ontvangers_geeft_geen_dubbele_adressen():
    users = {"jurian": {"email": "jurian@example.com", "alle_panden": True}}
    resultaat = ontvangers(users, "mahoniestraat", "huishouden", ["jurian@example.com"])
    assert resultaat == ["jurian@example.com"]


def test_ontvangers_dedupliceert_ongeacht_hoofdlettergebruik():
    # Justin's adres staat al (met een andere schrijfwijze) in EMAIL_BCC via
    # .env; als hij op de Mailvoorkeuren-pagina zijn eigen adres invult mag
    # dat niet als los, tweede adres in de lijst belanden (dubbele mail).
    users = {"justin": {"email": "Justin@Example.com", "alle_panden": True}}
    resultaat = ontvangers(users, "mahoniestraat", "huishouden", ["justin@example.com"])
    assert resultaat == ["justin@example.com"]


def test_laad_users_ontbrekend_bestand_geeft_leeg_dict(tmp_path):
    assert laad_users(str(tmp_path / "bestaat-niet.json")) == {}


def test_laad_users_leest_json(tmp_path):
    pad = tmp_path / "users.json"
    pad.write_text(json.dumps({"jurian": {"email": "jurian@example.com"}}))
    assert laad_users(str(pad)) == {"jurian": {"email": "jurian@example.com"}}


def test_notificatie_types_hebben_titel_en_uitleg():
    assert len(NOTIFICATIE_TYPES) >= 5
    for titel, uitleg in NOTIFICATIE_TYPES.values():
        assert titel and uitleg

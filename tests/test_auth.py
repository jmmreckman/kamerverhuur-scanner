from webapp.auth import User, user_uit_gegevens, verify_login
from werkzeug.security import generate_password_hash


def test_gebruiker_met_alle_panden_heeft_overal_toegang():
    user = User("jij", alle_panden=True, panden=[])
    assert user.heeft_toegang("mahoniestraat")
    assert user.heeft_toegang("een-nieuw-pand-van-later")


def test_gebruiker_met_specifieke_panden_heeft_alleen_daar_toegang():
    user = User("justin", alle_panden=False, panden=["mahoniestraat"])
    assert user.heeft_toegang("mahoniestraat")
    assert not user.heeft_toegang("ander-pand")


def test_verify_login_klopt_alleen_met_juist_wachtwoord():
    users = {"jij": {"wachtwoord_hash": generate_password_hash("geheim123"), "alle_panden": True, "panden": []}}
    assert verify_login(users, "jij", "geheim123")
    assert not verify_login(users, "jij", "verkeerd")
    assert not verify_login(users, "onbekend", "geheim123")


def test_user_uit_gegevens_leest_toegang_correct():
    gegevens = {"wachtwoord_hash": "x", "alle_panden": False, "panden": ["mahoniestraat", "pand2"]}
    user = user_uit_gegevens("justin", gegevens)
    assert user.heeft_toegang("pand2")
    assert not user.heeft_toegang("pand3")

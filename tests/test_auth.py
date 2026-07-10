import pytest
from webapp.auth import User, user_uit_gegevens, verify_login, zet_gebruiker
from werkzeug.security import check_password_hash, generate_password_hash


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


def test_mag_gebruikers_beheren_alleen_met_alle_panden():
    assert User("jij", alle_panden=True).mag_gebruikers_beheren()
    assert not User("justin", alle_panden=False, panden=["mahoniestraat"]).mag_gebruikers_beheren()


def test_zet_gebruiker_maakt_nieuwe_gebruiker_aan():
    users = zet_gebruiker({}, "nieuw", "geheim123", False, ["mahoniestraat"])
    assert check_password_hash(users["nieuw"]["wachtwoord_hash"], "geheim123")
    assert users["nieuw"]["alle_panden"] is False
    assert users["nieuw"]["panden"] == ["mahoniestraat"]


def test_zet_gebruiker_zonder_wachtwoord_behoudt_bestaand_wachtwoord():
    bestaande_hash = generate_password_hash("origineel")
    users = {"jij": {"wachtwoord_hash": bestaande_hash, "alle_panden": False, "panden": ["mahoniestraat"]}}
    zet_gebruiker(users, "jij", None, True, [])
    assert users["jij"]["wachtwoord_hash"] == bestaande_hash
    assert users["jij"]["alle_panden"] is True


def test_zet_gebruiker_zonder_wachtwoord_voor_nieuwe_gebruiker_geeft_fout():
    with pytest.raises(ValueError):
        zet_gebruiker({}, "nieuw", None, True, [])

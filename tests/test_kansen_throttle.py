from kansen_site.throttle import LoginThrottle


def test_blokkeert_na_te_veel_mislukte_pogingen():
    t = LoginThrottle(max_pogingen=3, venster_seconden=300)
    nu = 1000.0
    assert not t.geblokkeerd("1.2.3.4", nu=nu)
    for _ in range(3):
        t.registreer_mislukt("1.2.3.4", nu=nu)
    assert t.geblokkeerd("1.2.3.4", nu=nu)


def test_oude_pogingen_vervallen_na_het_venster():
    t = LoginThrottle(max_pogingen=3, venster_seconden=300)
    nu = 1000.0
    for _ in range(3):
        t.registreer_mislukt("1.2.3.4", nu=nu)
    assert t.geblokkeerd("1.2.3.4", nu=nu)
    assert not t.geblokkeerd("1.2.3.4", nu=nu + 301)


def test_geslaagde_login_wist_de_teller():
    t = LoginThrottle(max_pogingen=3, venster_seconden=300)
    nu = 1000.0
    for _ in range(3):
        t.registreer_mislukt("1.2.3.4", nu=nu)
    t.wis("1.2.3.4")
    assert not t.geblokkeerd("1.2.3.4", nu=nu)


def test_pogingen_zijn_per_ip_gescheiden():
    t = LoginThrottle(max_pogingen=3, venster_seconden=300)
    nu = 1000.0
    for _ in range(3):
        t.registreer_mislukt("1.1.1.1", nu=nu)
    assert t.geblokkeerd("1.1.1.1", nu=nu)
    assert not t.geblokkeerd("2.2.2.2", nu=nu)

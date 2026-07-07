from kamerverhuur_scanner.drive_client import _escape_q


def test_escape_q_escapt_enkele_quotes():
    assert _escape_q("kamer 1") == "kamer 1"
    assert _escape_q("O'Brien") == "O\\'Brien"


def test_escape_q_escapt_backslashes():
    assert _escape_q("a\\b") == "a\\\\b"


def test_escape_q_voorkomt_query_injectie():
    kwaadaardig = "x' or 'a'='a"
    geescaped = _escape_q(kwaadaardig)
    assert "' or '" not in geescaped

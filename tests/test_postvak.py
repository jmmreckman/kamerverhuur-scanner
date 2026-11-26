"""Pure tests voor het info@-postvak: het parsen van rauwe e-mail (headers,
body, bijlagen), het opschonen van HTML naar tekst, de antwoord-velden en het
uitlezen van UID/FLAGS uit een IMAP-fetch-regel. De IMAP-I/O en de routes
draaien in CI (webapp.app importeert zware deps die de sandbox niet bouwt)."""
from email.message import EmailMessage

from webapp import postvak


def test_parse_headers_decodeert_onderwerp_en_afzender():
    m = EmailMessage()
    m["From"] = "Jan de Tester <jan@example.com>"
    m["Subject"] = "Café rekening"
    m["Date"] = "Wed, 25 Nov 2026 14:30:00 +0100"
    m["Message-ID"] = "<abc123@example.com>"
    m.set_content("x")
    h = postvak.parse_headers(m.as_bytes())
    assert h["van_naam"] == "Jan de Tester"
    assert h["van_adres"] == "jan@example.com"
    assert h["onderwerp"] == "Café rekening"
    assert "25-11-2026" in h["datum"]
    assert h["message_id"] == "<abc123@example.com>"


def test_parse_headers_zonder_onderwerp():
    m = EmailMessage()
    m["From"] = "kaal@example.com"
    m.set_content("x")
    h = postvak.parse_headers(m.as_bytes())
    assert h["onderwerp"] == "(geen onderwerp)"
    assert h["van_naam"] == "kaal@example.com"  # geen naam -> val terug op adres


def test_parse_bericht_tekst_en_bijlage():
    m = EmailMessage()
    m["From"] = "A <a@x.nl>"
    m["Subject"] = "Hoi"
    m["Message-ID"] = "<m1@x>"
    m.set_content("Hallo dit is de tekst")
    m.add_attachment(b"PDFDATA", maintype="application", subtype="pdf", filename="factuur.pdf")
    b = postvak.parse_bericht(m.as_bytes())
    assert "Hallo dit is de tekst" in b["body"]
    assert len(b["bijlagen"]) == 1
    assert b["bijlagen"][0]["naam"] == "factuur.pdf"
    assert b["bijlagen"][0]["index"] == 0
    assert b["bijlagen"][0]["mime"] == "application/pdf"


def test_parse_bericht_html_only_wordt_veilige_tekst():
    m = EmailMessage()
    m["From"] = "A <a@x.nl>"
    m["Subject"] = "H"
    m.set_content("<p>Hallo <b>wereld</b></p><script>kwaad()</script>", subtype="html")
    b = postvak.parse_bericht(m.as_bytes())
    assert "Hallo" in b["body"] and "wereld" in b["body"]
    assert "<" not in b["body"] and "kwaad()" not in b["body"]


def test_html_naar_tekst_strip_tags_en_entiteiten():
    h = "<style>x{color:red}</style><p>Regel 1</p><br>Regel 2 &amp; meer"
    t = postvak.html_naar_tekst(h)
    assert "Regel 1" in t and "Regel 2 & meer" in t
    assert "<" not in t and "x{color" not in t


def test_antwoord_velden_prefixt_re_en_zet_headers():
    a = postvak.antwoord_velden({"onderwerp": "Vraag", "van_adres": "klant@x.nl", "message_id": "<q1@x>"})
    assert a["aan"] == "klant@x.nl"
    assert a["onderwerp"] == "Re: Vraag"
    assert a["headers"]["In-Reply-To"] == "<q1@x>"
    assert a["headers"]["References"] == "<q1@x>"


def test_antwoord_velden_dubbel_re_en_geen_message_id():
    a = postvak.antwoord_velden({"onderwerp": "Re: Vraag", "van_adres": "x@x.nl", "message_id": ""})
    assert a["onderwerp"] == "Re: Vraag"  # niet "Re: Re: ..."
    assert a["headers"] == {}             # geen threading-headers zonder message-id


def test_meta_haalt_uid_en_vlaggen():
    uid, vlaggen = postvak._meta(rb"1 (UID 4242 FLAGS (\Seen \Flagged) BODY[HEADER.FIELDS (FROM)] {123}")
    assert uid == "4242"
    assert "\\Seen" in vlaggen and "\\Flagged" in vlaggen
    uid2, v2 = postvak._meta(rb"2 (UID 7 FLAGS () BODY[] {10}")
    assert uid2 == "7" and v2 == set()

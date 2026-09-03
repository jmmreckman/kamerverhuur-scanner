"""Tests voor de NVM-/Move.nl-mailparser (tweede bron voor kansen.steenhub.nl).
De voorbeelden komen 1-op-1 uit een echte zoekopdracht-mail."""
from rotterdam_scanner.nvm_mail import parse_nvm_body

_MAIL = """Beste Jurian
Hierbij ontvang je een overzicht ...

Match: 100%
Westzeedijk 74 B3016 AG Rotterdam
Vraagprijs: € 485.000,- kosten koper
Bovenwoning | 63 m² | 3 kamers (2 slaapkamers)

Match: 100%
Nieuwe Binnenweg 127 C023014 GJ Rotterdam (Bolívar Residences (Nieuwe Binnenweg))
Vraagprijs: € 425.000,- kosten koper
Tussenverdieping | 68 m² | 2 kamers (1 slaapkamer)

Match: 100%
Hulshorststraat 2352573 EG 'S-Gravenhage
Vraagprijs: € 250.000,- kosten koper
Portiekflat | 69 m² | 4 kamers (3 slaapkamers)

Match: 100%
Hildegardisstraat 16 C3036 NW Rotterdam
Koopsom: € 320.000,- kosten koper
Portiekflat | 75 m² | 3 kamers (2 slaapkamers)

Match: 100%
2e Antonie Heinsiusstraat 692582 VS 'S-Gravenhage
Vraagprijs: € 695.000,- kosten koper
Herenhuis | 150 m² | 5 kamers (4 slaapkamers)

Match: 100%
Van Oosterwijk Bruynstraat 1 L2523 XS 'S-Gravenhage
Vraagprijs: € 417.500,- kosten koper
Tussenwoning | 91 m² / 137 m² | 5 kamers (4 slaapkamers)

Met vriendelijke groet, de makelaar
"""


def _op_id(woningen):
    return {w.object_id: w for w in woningen}


def test_parseert_alle_woningen_uit_de_mail():
    woningen, onherkend = parse_nvm_body(_MAIL)
    assert onherkend == []
    assert len(woningen) == 6


def test_basiswoning_velden_en_object_id():
    woningen, _ = parse_nvm_body(_MAIL)
    w = _op_id(woningen)["3016AG-74B"]
    assert w.straatnaam == "Westzeedijk"
    assert w.huisnummer == "74"
    assert w.toevoeging == "B"
    assert w.postcode == "3016AG"
    assert w.woonplaats == "Rotterdam"
    assert w.prijs == 485000
    assert w.oppervlakte_advertentie == 63
    assert w.bron == "nvm"
    assert w.url == ""  # NVM levert geen Funda-link; Funda-bron vult die aan


def test_toevoeging_met_letter_en_cijfers_en_complexnaam():
    # "127 C02" + postcode "3014 GJ", complexnaam tussen haakjes moet weg.
    woningen, _ = parse_nvm_body(_MAIL)
    w = _op_id(woningen)["3014GJ-127C02"]
    assert w.huisnummer == "127"
    assert w.toevoeging == "C02"
    assert w.woonplaats == "Rotterdam"


def test_geplakte_postcode_zonder_toevoeging():
    woningen, _ = parse_nvm_body(_MAIL)
    w = _op_id(woningen)["2573EG-235"]
    assert w.straatnaam == "Hulshorststraat"
    assert w.huisnummer == "235"
    assert w.toevoeging == ""
    assert w.woonplaats == "'S-Gravenhage"


def test_koopsom_wordt_ook_als_prijs_gelezen():
    woningen, _ = parse_nvm_body(_MAIL)
    w = _op_id(woningen)["3036NW-16C"]
    assert w.prijs == 320000


def test_straat_met_cijfer_aan_het_begin():
    # "2e Antonie Heinsiusstraat 69" - huisnummer is het láátste getal, niet de "2e".
    woningen, _ = parse_nvm_body(_MAIL)
    w = _op_id(woningen)["2582VS-69"]
    assert w.straatnaam == "2e Antonie Heinsiusstraat"
    assert w.huisnummer == "69"


def test_dubbele_oppervlakte_pakt_eerste():
    # "91 m² / 137 m²" -> woonoppervlak 91.
    woningen, _ = parse_nvm_body(_MAIL)
    w = _op_id(woningen)["2523XS-1L"]
    assert w.oppervlakte_advertentie == 91


def test_lege_mail_geeft_niks():
    woningen, onherkend = parse_nvm_body("Geen woningen hier.")
    assert woningen == []
    assert onherkend == []


def test_ontdubbelt_binnen_de_mail():
    body = _MAIL + """
Match: 100%
Westzeedijk 74 B3016 AG Rotterdam
Vraagprijs: € 485.000,- kosten koper
Bovenwoning | 63 m² | 3 kamers (2 slaapkamers)
"""
    woningen, _ = parse_nvm_body(body)
    assert sum(1 for w in woningen if w.object_id == "3016AG-74B") == 1

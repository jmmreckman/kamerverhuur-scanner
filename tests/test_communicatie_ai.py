"""Tests voor de pure delen van de AI-helpers (webapp/communicatie_ai.py):
stijl-nacheck, stopwoord-detectie, historie-formattering en prompt-bouw. De
Claude-aanroep zelf (genereer_*) wordt hier niet getest - die vereist een
API-key/netwerk."""
from webapp import communicatie_ai as ai


# --- schoon_stijl -----------------------------------------------------------

def test_schoon_stijl_haalt_puntkomma_weg():
    assert ";" not in ai.schoon_stijl("Dit klopt; dat ook.")


def test_schoon_stijl_vervangt_gedachtestreepje():
    uit = ai.schoon_stijl("De loodgieter komt langs — morgen rond tien uur.")
    assert "—" not in uit and "–" not in uit
    assert "morgen rond tien uur" in uit


def test_schoon_stijl_ruimt_dubbele_leestekens_op():
    # puntkomma gevolgd door spatie -> nette komma, geen " ," of dubbele komma
    uit = ai.schoon_stijl("Hoi Jane ; dit is geregeld")
    assert " ," not in uit
    assert ", ," not in uit
    assert "Hoi Jane, dit is geregeld" == uit


def test_schoon_stijl_laat_normale_tekst_heel():
    tekst = "Hoi Jane, de kraan is gemaakt. Laat maar weten als er nog iets is."
    assert ai.schoon_stijl(tekst) == tekst


def test_schoon_stijl_leeg():
    assert ai.schoon_stijl("") == ""


# --- vind_ai_stopwoorden ----------------------------------------------------

def test_vind_ai_stopwoorden_detecteert():
    gevonden = ai.vind_ai_stopwoorden("Uiteraard regel ik dat. Ik sta voor je klaar!")
    assert "uiteraard" in gevonden
    assert "ik sta voor je klaar" in gevonden


def test_vind_ai_stopwoorden_leeg_bij_schone_tekst():
    assert ai.vind_ai_stopwoorden("Hoi, de kraan is gemaakt. Groeten.") == []


# --- formatteer_geschiedenis ------------------------------------------------

def test_formatteer_geschiedenis_labelt_richting_en_datum():
    berichten = [
        {"datum": "2025-05-01T10:00:00+00:00", "richting": "in", "van": "jane@x.nl",
         "onderwerp": "Kraan lekt", "body": "De kraan lekt al dagen."},
        {"datum": "2025-05-02T09:00:00+00:00", "richting": "uit", "van": "info@steenhub.nl",
         "onderwerp": None, "body": "Ik stuur de loodgieter."},
    ]
    uit = ai.formatteer_geschiedenis(berichten)
    assert "[2025-05-01] Huurder (jane@x.nl)" in uit
    assert "onderwerp: Kraan lekt" in uit
    assert "[2025-05-02] Beheerder (jij)" in uit
    assert "Ik stuur de loodgieter." in uit


def test_formatteer_geschiedenis_leeg():
    assert ai.formatteer_geschiedenis([]) == ""


# --- prompt-bouw ------------------------------------------------------------

def test_bouw_antwoord_prompt_bevat_context_en_stijlregels():
    systeem, user = ai.bouw_antwoord_prompt(
        pand_naam="Mahoniestraat 15", huurder_naam="Jane Doe",
        geschiedenis_tekst="[2025-05-01] Huurder: kraan lekt",
        extra_instructie="Noem dat de loodgieter morgen komt.",
    )
    assert "puntkomma" in systeem.lower()
    assert "Mahoniestraat 15" in user and "Jane Doe" in user
    assert "kraan lekt" in user
    assert "loodgieter morgen komt" in user


def test_bouw_antwoord_prompt_met_samenvatting_als_achtergrond():
    _systeem, user = ai.bouw_antwoord_prompt(
        pand_naam="P", huurder_naam="H", geschiedenis_tekst="recent bericht",
        samenvatting="Rustige huurder, betaalt altijd op tijd.",
    )
    assert "Achtergrond" in user
    assert "betaalt altijd op tijd" in user
    assert "recent bericht" in user


def test_bouw_antwoord_prompt_zonder_historie():
    _systeem, user = ai.bouw_antwoord_prompt(
        pand_naam="P", huurder_naam="H", geschiedenis_tekst="",
    )
    assert "nog geen eerdere berichten" in user


def test_bouw_vakman_mail_bevat_vaste_instructies():
    onderwerp, body = ai.bouw_vakman_mail(
        vakman_naam="Piet", vak="loodgieter", huurder_naam="Jane Doe",
        adres="Mahoniestraat 15", reden="lekkage onder de wastafel",
        beheerder_telefoon="06-44021086",
    )
    assert "Mahoniestraat 15" in onderwerp
    assert "Jane Doe" in body and "lekkage onder de wastafel" in body
    assert "factuur rechtstreeks naar mij" in body
    assert "150 euro" in body and "06-44021086" in body
    # stijlregels: geen puntkomma's/gedachtestreepjes
    assert ";" not in body and "—" not in body


def test_bouw_vakman_mail_zonder_telefoonnummer():
    _onderwerp, body = ai.bouw_vakman_mail(
        vakman_naam="Piet", vak=None, huurder_naam="Jane", adres="P 1", reden="x",
    )
    assert "150 euro" in body
    assert "06-" not in body  # geen verzonnen nummer


def test_chunk_berichten_splitst_en_behoudt_volgorde():
    berichten = [{"body": "x" * 100} for _ in range(10)]  # ~220 tekens per bericht (incl. +120)
    chunks = ai._chunk_berichten(berichten, max_chars=500)  # ~2 berichten per chunk
    # alle berichten zitten erin, volgorde behouden
    assert sum(len(c) for c in chunks) == 10
    assert len(chunks) >= 4
    # geen enkel (niet-eerste) chunk overschrijdt grof de grens
    for c in chunks:
        assert len(c) <= 3


def test_chunk_berichten_kort_blijft_een_stuk():
    berichten = [{"body": "kort"} for _ in range(3)]
    assert len(ai._chunk_berichten(berichten, max_chars=40_000)) == 1


def test_bouw_samenvatting_prompt():
    systeem, user = ai.bouw_samenvatting_prompt(
        huurder_naam="Jane Doe", geschiedenis_tekst="[2025-05-01] Huurder: kraan lekt",
    )
    assert "samen" in systeem.lower()  # "Je vat ... samen"
    assert "Jane Doe" in user and "kraan lekt" in user
    assert "samenvatting" in user.lower()

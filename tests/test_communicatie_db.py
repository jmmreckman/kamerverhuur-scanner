"""Tests voor de pure SQLite-opslaglaag van de communicatie-/onderhoudsmodule
(webapp/communicatie_db.py). Geen Flask, geen netwerk - draait gewoon in de
sandbox op een tijdelijk db-bestand."""
import pytest

from webapp import communicatie_db as db


@pytest.fixture()
def conn(tmp_path):
    c = db.verbind(str(tmp_path / "communicatie.db"))
    yield c
    c.close()


# --- contacten --------------------------------------------------------------

def test_upsert_contact_maakt_nieuw_en_koppelt_emails(conn):
    cid = db.upsert_contact(conn, "Jane Doe", pand_slug="mahoniestraat", kamer="BG tuin",
                            telefoon="0612345678", emails=["Jane@Example.com"])
    rij = db.get_contact(conn, cid)
    assert rij["naam"] == "Jane Doe"
    assert rij["pand_slug"] == "mahoniestraat"
    # e-mail genormaliseerd (lowercase/trim)
    assert db.emails_van_contact(conn, cid) == ["jane@example.com"]


def test_upsert_contact_matcht_op_email_en_voegt_niet_dubbel_toe(conn):
    cid1 = db.upsert_contact(conn, "Jane Doe", emails=["jane@example.com"])
    # Zelfde e-mail, andere (vollere) naam -> zelfde contact, naam bijgewerkt.
    cid2 = db.upsert_contact(conn, "Jane Amanda Doe", emails=["jane@example.com"],
                             telefoon="0611111111")
    assert cid1 == cid2
    rij = db.get_contact(conn, cid1)
    assert rij["naam"] == "Jane Amanda Doe"
    assert rij["telefoon"] == "0611111111"


def test_upsert_contact_overschrijft_geen_bestaande_waarde_met_leeg(conn):
    cid = db.upsert_contact(conn, "Jane", telefoon="0612345678", emails=["j@x.nl"])
    # Tweede seed zonder telefoon mag de bestaande niet wissen.
    db.upsert_contact(conn, "Jane", emails=["j@x.nl"], telefoon=None)
    assert db.get_contact(conn, cid)["telefoon"] == "0612345678"


def test_contact_kan_meerdere_emails_hebben(conn):
    cid = db.upsert_contact(conn, "Jane", emails=["jane@example.com"])
    db.upsert_contact(conn, "Jane", emails=["jane@example.com", "jane.doe@hotmail.com"])
    assert set(db.emails_van_contact(conn, cid)) == {"jane@example.com", "jane.doe@hotmail.com"}
    assert db.get_contact_op_email(conn, "JANE.DOE@hotmail.com")["id"] == cid


def test_zonder_email_altijd_nieuw_contact(conn):
    a = db.upsert_contact(conn, "Naamloos een")
    b = db.upsert_contact(conn, "Naamloos een")
    assert a != b


def test_lijst_contacten_filtert_op_pand_en_actief(conn):
    db.upsert_contact(conn, "A", pand_slug="p1", emails=["a@x.nl"])
    db.upsert_contact(conn, "B", pand_slug="p2", emails=["b@x.nl"])
    namen = [r["naam"] for r in db.lijst_contacten(conn, pand_slugs=["p1"])]
    assert namen == ["A"]
    # lege toegangslijst -> niets
    assert db.lijst_contacten(conn, pand_slugs=[]) == []


def test_zet_samenvatting(conn):
    cid = db.upsert_contact(conn, "Jane", emails=["j@x.nl"])
    db.zet_samenvatting(conn, cid, "Rustige huurder, vroeg in mei 2025 om een nieuwe sleutel.")
    rij = db.get_contact(conn, cid)
    assert "sleutel" in rij["samenvatting"]
    assert rij["samenvatting_bijgewerkt"]


# --- berichten --------------------------------------------------------------

def test_voeg_bericht_toe_en_tijdlijn_chronologisch(conn):
    cid = db.upsert_contact(conn, "Jane", emails=["j@x.nl"])
    db.voeg_bericht_toe(conn, contact_id=cid, pand_slug="p1", kanaal="info",
                        richting="in", body="tweede", datum="2025-06-01T10:00:00+00:00")
    db.voeg_bericht_toe(conn, contact_id=cid, pand_slug="p1", kanaal="info",
                        richting="uit", body="eerste", datum="2025-05-01T10:00:00+00:00")
    bodies = [b["body"] for b in db.berichten_van_contact(conn, cid)]
    assert bodies == ["eerste", "tweede"]


def test_bericht_dedup_op_message_id(conn):
    cid = db.upsert_contact(conn, "Jane", emails=["j@x.nl"])
    eerste = db.voeg_bericht_toe(conn, contact_id=cid, pand_slug="p1", kanaal="gmail-historie",
                                 richting="in", body="x", message_id="<abc@mail>")
    tweede = db.voeg_bericht_toe(conn, contact_id=cid, pand_slug="p1", kanaal="gmail-historie",
                                 richting="in", body="x", message_id="<abc@mail>")
    assert eerste is not None
    assert tweede is None  # dedup
    assert len(db.berichten_van_contact(conn, cid)) == 1


# --- klussen ----------------------------------------------------------------

def test_maak_klus_en_lijst_nieuwste_boven(conn):
    k1 = db.maak_klus(conn, titel="Lekkage", pand_slug="p1")
    k2 = db.maak_klus(conn, titel="Kapotte deur", pand_slug="p1")
    # k2 is nieuwer -> bovenaan
    ids = [k["id"] for k in db.lijst_klussen(conn, pand_slugs=["p1"])]
    assert ids == [k2, k1]


def test_lijst_klussen_alleen_open_en_pandfilter(conn):
    k_open = db.maak_klus(conn, titel="Open", pand_slug="p1")
    k_klaar = db.maak_klus(conn, titel="Klaar", pand_slug="p1")
    db.zet_klus_status(conn, k_klaar, db.KLUS_AFGEROND)
    open_ids = [k["id"] for k in db.lijst_klussen(conn, pand_slugs=["p1"], alleen_open=True)]
    assert open_ids == [k_open]
    # andere pand -> niet zichtbaar
    assert db.lijst_klussen(conn, pand_slugs=["p2"]) == []


def test_zet_klus_status_afgerond_zet_datum(conn):
    k = db.maak_klus(conn, titel="X", pand_slug="p1")
    assert db.get_klus(conn, k)["afgerond_op"] is None
    db.zet_klus_status(conn, k, db.KLUS_AFGEROND)
    assert db.get_klus(conn, k)["afgerond_op"] is not None
    assert db.get_klus(conn, k)["status"] == db.KLUS_AFGEROND


def test_koppel_vakman(conn):
    v = db.voeg_vakman_toe(conn, "Loodgieter Piet", vak="loodgieter")
    k = db.maak_klus(conn, titel="Lekkage", pand_slug="p1")
    db.koppel_vakman(conn, k, v)
    assert db.get_klus(conn, k)["vakman_id"] == v


# --- vakmannen --------------------------------------------------------------

def test_vakmannen_crud_en_actief_filter(conn):
    v1 = db.voeg_vakman_toe(conn, "Piet", vak="loodgieter", telefoon="06")
    v2 = db.voeg_vakman_toe(conn, "Klaas", vak="timmerman")
    assert {r["naam"] for r in db.lijst_vakmannen(conn)} == {"Piet", "Klaas"}
    db.zet_vakman_actief(conn, v2, False)
    assert {r["naam"] for r in db.lijst_vakmannen(conn)} == {"Piet"}
    assert db.get_vakman(conn, v1)["vak"] == "loodgieter"


# --- acties -----------------------------------------------------------------

def test_acties_maken_lijst_bijwerken_verzenden(conn):
    cid = db.upsert_contact(conn, "Jane", pand_slug="p1", emails=["j@x.nl"])
    a = db.maak_actie(conn, type="concept-huurder", concept_body="Hoi Jane, ...",
                      concept_onderwerp="Je vraag", contact_id=cid, pand_slug="p1",
                      ontvanger="j@x.nl")
    assert [r["id"] for r in db.lijst_acties(conn, pand_slugs=["p1"])] == [a]
    assert db.tel_open_acties(conn, pand_slugs=["p1"]) == 1
    # concept aanpassen voor goedkeuring
    db.werk_actie_concept_bij(conn, a, "Nieuw onderwerp", "Aangepaste tekst")
    assert db.get_actie(conn, a)["concept_body"] == "Aangepaste tekst"
    # verzenden -> uit de open-lijst, verzonden_op gezet
    db.zet_actie_status(conn, a, db.ACTIE_VERZONDEN)
    assert db.lijst_acties(conn, pand_slugs=["p1"]) == []
    assert db.get_actie(conn, a)["verzonden_op"] is not None
    assert db.tel_open_acties(conn, pand_slugs=["p1"]) == 0


def test_acties_pandfilter_respecteert_toegang(conn):
    db.maak_actie(conn, type="concept-huurder", concept_body="x", pand_slug="p1")
    db.maak_actie(conn, type="concept-huurder", concept_body="y", pand_slug="p2")
    assert db.tel_open_acties(conn, pand_slugs=["p1"]) == 1
    # geen toegang tot enig pand -> niets
    assert db.lijst_acties(conn, pand_slugs=[]) == []
    assert db.tel_open_acties(conn, pand_slugs=[]) == 0


def test_init_db_is_idempotent(tmp_path):
    p = str(tmp_path / "x.db")
    c1 = db.verbind(p)
    db.upsert_contact(c1, "Jane", emails=["j@x.nl"])
    c1.close()
    # Opnieuw verbinden mag niets stukmaken en de data behouden.
    c2 = db.verbind(p)
    assert len(db.lijst_contacten(c2)) == 1
    c2.close()

"""Tests voor de 'laatste controle'-cache - moet in een instelbare map
opgeslagen worden (STATE_DIR), anders is de cache na elke herbuild van de
Docker-container weer leeg (niet-volume paden worden dan gewist)."""
from datetime import date
from decimal import Decimal

from kamerverhuur_scanner import state
from kamerverhuur_scanner.models import Payment, Status, Tenant, TenantResult


def _result() -> TenantResult:
    tenant = Tenant(row_index=2, naam="Jan", kamer="1", verwacht_bedrag=Decimal("650.00"))
    return TenantResult(tenant=tenant, ontvangen_bedrag=Decimal("650.00"), status=Status.BETAALD)


def test_save_en_load_gebruiken_state_dir(tmp_path):
    state.save("mahoniestraat", [_result()], 0, state_dir=str(tmp_path))

    bestanden = list(tmp_path.iterdir())
    assert len(bestanden) == 1
    assert bestanden[0].name == "laatste_resultaat_mahoniestraat.json"

    geladen = state.load("mahoniestraat", state_dir=str(tmp_path))
    assert geladen is not None
    assert geladen["resultaten"][0]["kamer"] == "1"


def test_save_zonder_unmatched_payments_geeft_lege_lijst(tmp_path):
    # Bestaand gedrag (bv. oudere aanroepen die alleen het aantal meegeven,
    # niet de details zelf) moet niet crashen - gewoon een lege lijst.
    state.save("mahoniestraat", [_result()], 2, state_dir=str(tmp_path))
    geladen = state.load("mahoniestraat", state_dir=str(tmp_path))
    assert geladen["niet_gekoppelde_betalingen"] == 2
    assert geladen["niet_gekoppelde_betalingen_lijst"] == []


def test_save_bewaart_details_van_niet_gekoppelde_betalingen(tmp_path):
    # Zonder dit blijft de betalingenpagina bij een gewoon bezoek (buiten een
    # verse "Nu controleren"-klik om) leeg, ook al meldt het dashboard wel
    # "X betaling(en) niet gekoppeld" - de details werden voorheen nergens
    # bewaard, alleen het aantal.
    betaling = Payment(
        bedrag=Decimal("650.00"), valuta="EUR", tegenpartij_naam="M Poncea Andronescu",
        tegenpartij_iban="NL91ABNA0417164300", omschrijving="Huur juli", datum=date(2026, 7, 24),
    )
    state.save("mahoniestraat", [_result()], 1, state_dir=str(tmp_path), unmatched_payments=[betaling])

    geladen = state.load("mahoniestraat", state_dir=str(tmp_path))
    regel = geladen["niet_gekoppelde_betalingen_lijst"][0]
    assert regel["datum"] == "24-07-2026"
    assert regel["tegenpartij_naam"] == "M Poncea Andronescu"
    assert regel["bedrag"] == "650.00"
    assert regel["omschrijving"] == "Huur juli"


def test_load_in_andere_state_dir_vindt_niets(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    state.save("mahoniestraat", [_result()], 0, state_dir=str(tmp_path / "a"))
    assert state.load("mahoniestraat", state_dir=str(tmp_path / "b")) is None


def test_email_verzonden_op_zonder_markering_geeft_none(tmp_path):
    assert state.email_verzonden_op("mahoniestraat", "3", "herinnering", "2026-07", state_dir=str(tmp_path)) is None


def test_markeer_email_verzonden_en_opvragen(tmp_path):
    state.markeer_email_verzonden("mahoniestraat", "3", "herinnering", "2026-07", state_dir=str(tmp_path))

    verzonden_op = state.email_verzonden_op("mahoniestraat", "3", "herinnering", "2026-07", state_dir=str(tmp_path))
    assert verzonden_op is not None


def test_markeer_email_verzonden_onderscheidt_soort_en_kamer(tmp_path):
    state.markeer_email_verzonden("mahoniestraat", "3", "herinnering", "2026-07", state_dir=str(tmp_path))

    # andere soort, andere kamer: geen van beide gemarkeerd
    assert state.email_verzonden_op("mahoniestraat", "3", "ingebrekestelling", "2026-07", state_dir=str(tmp_path)) is None
    assert state.email_verzonden_op("mahoniestraat", "4", "herinnering", "2026-07", state_dir=str(tmp_path)) is None


def test_markeer_email_verzonden_reset_bij_nieuwe_maand(tmp_path):
    state.markeer_email_verzonden("mahoniestraat", "3", "herinnering", "2026-06", state_dir=str(tmp_path))
    # een nieuwe maand heeft nog geen eigen markering, ook al is dezelfde
    # kamer/soort al eens eerder (in een vorige maand) verzonden
    assert state.email_verzonden_op("mahoniestraat", "3", "herinnering", "2026-07", state_dir=str(tmp_path)) is None


def test_aanzegging_is_afgehandeld_zonder_markering_is_false(tmp_path):
    assert state.aanzegging_is_afgehandeld("mahoniestraat", "3", "2026-08-31", state_dir=str(tmp_path)) is False


def test_markeer_aanzegging_afgehandeld_en_opvragen(tmp_path):
    state.markeer_aanzegging_afgehandeld("mahoniestraat", "3", "2026-08-31", state_dir=str(tmp_path))
    assert state.aanzegging_is_afgehandeld("mahoniestraat", "3", "2026-08-31", state_dir=str(tmp_path)) is True


def test_markeer_aanzegging_afgehandeld_reset_bij_nieuwe_einddatum(tmp_path):
    state.markeer_aanzegging_afgehandeld("mahoniestraat", "3", "2026-08-31", state_dir=str(tmp_path))
    # een nieuw contract met een andere einddatum voor dezelfde kamer is een
    # nieuwe aanzegging - de oude markering geldt daar niet voor
    assert state.aanzegging_is_afgehandeld("mahoniestraat", "3", "2027-01-31", state_dir=str(tmp_path)) is False


def test_winst_geschiedenis_zonder_snapshots_geeft_lege_lijst(tmp_path):
    assert state.laad_winst_geschiedenis("mahoniestraat", state_dir=str(tmp_path)) == []


def test_voeg_winst_snapshot_toe_en_laad(tmp_path):
    state.voeg_winst_snapshot_toe("mahoniestraat", Decimal("1234.56"), state_dir=str(tmp_path))
    geschiedenis = state.laad_winst_geschiedenis("mahoniestraat", state_dir=str(tmp_path))
    assert len(geschiedenis) == 1
    assert geschiedenis[0]["winst"] == "1234.56"


def test_voeg_winst_snapshot_toe_zelfde_dag_overschrijft_ipv_dupliceert(tmp_path):
    state.voeg_winst_snapshot_toe("mahoniestraat", Decimal("1000.00"), state_dir=str(tmp_path))
    state.voeg_winst_snapshot_toe("mahoniestraat", Decimal("1100.00"), state_dir=str(tmp_path))
    geschiedenis = state.laad_winst_geschiedenis("mahoniestraat", state_dir=str(tmp_path))
    assert len(geschiedenis) == 1
    assert geschiedenis[0]["winst"] == "1100.00"


def test_winst_geschiedenis_per_pand_gescheiden(tmp_path):
    state.voeg_winst_snapshot_toe("mahoniestraat", Decimal("1000.00"), state_dir=str(tmp_path))
    state.voeg_winst_snapshot_toe("baumannlaan", Decimal("500.00"), state_dir=str(tmp_path))
    assert len(state.laad_winst_geschiedenis("mahoniestraat", state_dir=str(tmp_path))) == 1
    assert len(state.laad_winst_geschiedenis("baumannlaan", state_dir=str(tmp_path))) == 1


def test_genegeerde_lasten_zonder_markering_geeft_leeg_dict(tmp_path):
    assert state.laad_genegeerde_lasten("mahoniestraat", state_dir=str(tmp_path)) == {}


def test_negeer_last_en_opvragen(tmp_path):
    state.negeer_last("mahoniestraat", "nl91abna0417164300", "Jur", state_dir=str(tmp_path))
    assert state.laad_genegeerde_lasten("mahoniestraat", state_dir=str(tmp_path)) == {
        "nl91abna0417164300": "Jur",
    }


def test_verwijder_genegeerde_last_zet_hem_weer_terug(tmp_path):
    state.negeer_last("mahoniestraat", "nl91abna0417164300", "Jur", state_dir=str(tmp_path))
    state.verwijder_genegeerde_last("mahoniestraat", "nl91abna0417164300", state_dir=str(tmp_path))
    assert state.laad_genegeerde_lasten("mahoniestraat", state_dir=str(tmp_path)) == {}


def test_verwijder_genegeerde_last_zonder_bestand_faalt_niet(tmp_path):
    state.verwijder_genegeerde_last("mahoniestraat", "onbekend", state_dir=str(tmp_path))


def test_genegeerde_lasten_per_pand_gescheiden(tmp_path):
    state.negeer_last("mahoniestraat", "nl91abna0417164300", "Jur", state_dir=str(tmp_path))
    assert state.laad_genegeerde_lasten("baumannlaan", state_dir=str(tmp_path)) == {}

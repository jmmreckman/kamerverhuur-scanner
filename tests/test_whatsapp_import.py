"""Tests voor de WhatsApp-exportparser (webapp/whatsapp_import.py). Puur, geen
netwerk of deps - draait gewoon in de sandbox."""
from webapp import whatsapp_import as wa


def test_ios_formaat_met_blokhaken_en_seconden():
    tekst = "[25-10-2026, 14:12:33] Nushka: Hoi, de kraan lekt weer\n" \
            "[25-10-2026, 14:15:01] Jurian: Ik stuur de loodgieter"
    berichten = wa.parse_whatsapp_export(tekst, eigen_namen={"Jurian"})
    assert len(berichten) == 2
    assert berichten[0]["afzender"] == "Nushka"
    assert berichten[0]["richting"] == "in"
    assert berichten[0]["datum"] == "2026-10-25T14:12:33+00:00"
    assert berichten[1]["richting"] == "uit"  # Jurian = eigen naam


def test_android_formaat_met_streepje_en_slash():
    tekst = "25/10/2026, 14:12 - Nushka: ok\n" \
            "25/10/2026, 14:13 - Jurian: top"
    berichten = wa.parse_whatsapp_export(tekst, eigen_namen={"jurian"})
    assert berichten[0]["datum"] == "2026-10-25T14:12:00+00:00"
    assert berichten[0]["richting"] == "in"
    assert berichten[1]["richting"] == "uit"


def test_iso_datum_jaar_vooraan():
    tekst = "2026-10-25, 09:05 - Nushka: goedemorgen"
    berichten = wa.parse_whatsapp_export(tekst, eigen_namen=set())
    assert berichten[0]["datum"] == "2026-10-25T09:05:00+00:00"


def test_twaalfuurs_tijd_pm():
    tekst = "[25/10/2026, 1:05:00 PM] Nushka: hoi"
    berichten = wa.parse_whatsapp_export(tekst, eigen_namen=set())
    assert berichten[0]["datum"] == "2026-10-25T13:05:00+00:00"


def test_tweecijferig_jaar():
    tekst = "25-10-26 14:12 - Nushka: hoi"
    berichten = wa.parse_whatsapp_export(tekst, eigen_namen=set())
    assert berichten[0]["datum"].startswith("2026-10-25T14:12")


def test_meerregelig_bericht_wordt_samengevoegd():
    tekst = "[25-10-2026, 14:12:00] Nushka: regel een\n" \
            "regel twee\n" \
            "regel drie\n" \
            "[25-10-2026, 14:20:00] Jurian: antwoord"
    berichten = wa.parse_whatsapp_export(tekst, eigen_namen={"Jurian"})
    assert len(berichten) == 2
    assert berichten[0]["body"] == "regel een\nregel twee\nregel drie"


def test_systeemregels_worden_overgeslagen():
    tekst = "[25-10-2026, 14:00:00] Berichten en gesprekken zijn end-to-end versleuteld.\n" \
            "[25-10-2026, 14:12:00] Nushka: <media weggelaten>\n" \
            "[25-10-2026, 14:13:00] Nushka: echt bericht"
    berichten = wa.parse_whatsapp_export(tekst, eigen_namen=set())
    # Alleen het echte bericht blijft over.
    assert len(berichten) == 1
    assert berichten[0]["body"] == "echt bericht"


def test_afzender_niet_in_eigen_namen_is_inkomend():
    tekst = "[25-10-2026, 14:12:00] Onbekend Iemand: hoi"
    berichten = wa.parse_whatsapp_export(tekst, eigen_namen={"Jurian", "Justin"})
    assert berichten[0]["richting"] == "in"


def test_lege_export_geeft_lege_lijst():
    assert wa.parse_whatsapp_export("", eigen_namen={"Jurian"}) == []
    assert wa.parse_whatsapp_export("   \n  \n", eigen_namen={"Jurian"}) == []


def test_synthetiseer_message_id_is_stabiel_en_uniek():
    a = wa.synthetiseer_message_id(1, "2026-10-25T14:12:00+00:00", "Nushka", "hoi")
    b = wa.synthetiseer_message_id(1, "2026-10-25T14:12:00+00:00", "Nushka", "hoi")
    c = wa.synthetiseer_message_id(1, "2026-10-25T14:12:00+00:00", "Nushka", "iets anders")
    assert a == b          # zelfde bericht -> zelfde id (idempotent importeren)
    assert a != c          # andere inhoud -> ander id
    assert a.startswith("wa:1:")

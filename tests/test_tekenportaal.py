"""Tests voor het losse tekenportaal (webapp/tekenportaal.py): PDF uploaden,
velden plaatsen, per-ondertekenaar tokens, ondertekenen en de getekende PDF +
ondertekeningsverklaring genereren."""
import base64
from types import SimpleNamespace

import fitz
import pytest

from kamerverhuur_scanner import drive_sync
from webapp import tekenportaal as tp


def _mini_pdf(paginas: int = 2) -> bytes:
    doc = fitz.open()
    for i in range(paginas):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), f"Pagina {i + 1}")
    data = doc.tobytes()
    doc.close()
    return data


def _mini_handtekening_payload() -> str:
    doc = fitz.open()
    page = doc.new_page(width=300, height=90)
    page.draw_line((10, 45), (290, 45), width=2)
    png = page.get_pixmap(alpha=False).tobytes("png")
    doc.close()
    return tp.handtekening_base64_uit_data_url("data:image/png;base64," + base64.b64encode(png).decode())


def _tot_en_met_verzonden(state_dir):
    meta = tp.maak_document(state_dir, "Samenwerkingscontract", _mini_pdf(2), "contract.pdf", "jurian")
    tp.zet_velden(state_dir, meta["doc_id"], [
        {"pagina": 0, "x": 0.1, "y": 0.8, "breedte": 0.26, "hoogte": 0.07, "email": "a@x.nl", "naam": "Alice"},
        {"pagina": 1, "x": 0.5, "y": 0.8, "breedte": 0.26, "hoogte": 0.07, "email": "b@y.nl", "naam": "Bob"},
    ])
    return tp.bereid_verzending_voor(state_dir, meta["doc_id"])


def test_maak_document_weigert_niet_pdf(tmp_path):
    with pytest.raises(ValueError):
        tp.maak_document(str(tmp_path), "Titel", b"dit is geen pdf", "x.pdf", "jurian")


def test_maak_document_weigert_te_groot(tmp_path):
    groot = b"%PDF-1.4" + b"0" * (tp.MAX_PDF_BYTES + 1)
    with pytest.raises(ValueError):
        tp.maak_document(str(tmp_path), "Titel", groot, "x.pdf", "jurian")


def test_maak_document_en_render(tmp_path):
    meta = tp.maak_document(str(tmp_path), "Mijn contract", _mini_pdf(2), "c.pdf", "jurian")
    assert meta["status"] == "concept"
    assert tp.pagina_aantal(str(tmp_path), meta["doc_id"]) == 2
    png = tp.render_pagina_png(str(tmp_path), meta["doc_id"], 0)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_zet_velden_valideert(tmp_path):
    meta = tp.maak_document(str(tmp_path), "T", _mini_pdf(1), "c.pdf", "jurian")
    did = meta["doc_id"]
    with pytest.raises(ValueError):  # leeg
        tp.zet_velden(str(tmp_path), did, [])
    with pytest.raises(ValueError):  # ongeldig mailadres
        tp.zet_velden(str(tmp_path), did, [{"pagina": 0, "x": 0.1, "y": 0.1, "email": "kapot"}])
    with pytest.raises(ValueError):  # niet-bestaande pagina
        tp.zet_velden(str(tmp_path), did, [{"pagina": 9, "x": 0.1, "y": 0.1, "email": "a@x.nl"}])


def test_zet_velden_clamp_en_id(tmp_path):
    meta = tp.maak_document(str(tmp_path), "T", _mini_pdf(1), "c.pdf", "jurian")
    meta = tp.zet_velden(str(tmp_path), meta["doc_id"], [
        {"pagina": 0, "x": -1, "y": 2, "breedte": 5, "hoogte": 0.07, "email": "a@x.nl"},
    ])
    v = meta["velden"][0]
    assert v["x"] == 0.0 and v["y"] == 1.0 and v["breedte"] == 1.0
    assert v["veld_id"]


def test_verzenden_maakt_tokens_per_uniek_adres(tmp_path):
    meta = _tot_en_met_verzonden(str(tmp_path))
    assert meta["status"] == "verzonden"
    assert meta["verzonden_op"]
    emails = sorted(o["email"] for o in meta["ondertekenaars"])
    assert emails == ["a@x.nl", "b@y.nl"]
    assert all(o["token"] for o in meta["ondertekenaars"])


def test_verzenden_is_idempotent(tmp_path):
    meta = _tot_en_met_verzonden(str(tmp_path))
    tokens1 = sorted(o["token"] for o in meta["ondertekenaars"])
    meta2 = tp.bereid_verzending_voor(str(tmp_path), meta["doc_id"])
    assert sorted(o["token"] for o in meta2["ondertekenaars"]) == tokens1  # geen nieuwe tokens


def test_velden_na_verzenden_niet_meer_wijzigbaar(tmp_path):
    meta = _tot_en_met_verzonden(str(tmp_path))
    with pytest.raises(ValueError):
        tp.zet_velden(str(tmp_path), meta["doc_id"], [
            {"pagina": 0, "x": 0.1, "y": 0.1, "email": "c@z.nl"},
        ])


def test_zelfde_adres_meerdere_velden_is_een_ondertekenaar(tmp_path):
    meta = tp.maak_document(str(tmp_path), "T", _mini_pdf(1), "c.pdf", "jurian")
    tp.zet_velden(str(tmp_path), meta["doc_id"], [
        {"pagina": 0, "x": 0.1, "y": 0.2, "email": "a@x.nl", "naam": "Alice"},
        {"pagina": 0, "x": 0.1, "y": 0.6, "email": "a@x.nl"},
    ])
    meta = tp.bereid_verzending_voor(str(tmp_path), meta["doc_id"])
    assert len(meta["ondertekenaars"]) == 1
    assert meta["ondertekenaars"][0]["naam"] == "Alice"


def test_tekenen_en_getekende_pdf(tmp_path):
    sd = str(tmp_path)
    meta = _tot_en_met_verzonden(sd)
    payload = _mini_handtekening_payload()
    assert payload

    for email, naam in (("a@x.nl", "Alice Jansen"), ("b@y.nl", "Bob de Vries")):
        o = next(o for o in meta["ondertekenaars"] if o["email"] == email)
        assert tp.zoek_via_token(sd, o["token"]) is not None
        tp.markeer_getekend(sd, meta["doc_id"], email, "1.2.3.4", "Mozilla/Test", naam, payload)

    meta = tp.lees_meta(sd, meta["doc_id"])
    assert tp.alles_getekend(meta)

    naam, out = tp.genereer_getekend_pdf(sd, meta["doc_id"])
    assert naam.endswith("getekend.pdf")
    chk = fitz.open(stream=out, filetype="pdf")
    tekst = chk[chk.page_count - 1].get_text()
    aantal = chk.page_count
    chk.close()
    assert aantal == 3  # 2 origineel + 1 verklaring
    assert "Ondertekeningsverklaring" in tekst
    assert "1.2.3.4" in tekst
    assert "Alice Jansen" in tekst
    assert meta["origineel_sha256"][:16] in tekst

    meta = tp.lees_meta(sd, meta["doc_id"])
    assert meta["status"] == "afgerond"
    assert tp.lees_getekend_pdf(sd, meta["doc_id"]) is not None


def test_markeer_getekend_is_idempotent(tmp_path):
    sd = str(tmp_path)
    meta = _tot_en_met_verzonden(sd)
    payload = _mini_handtekening_payload()
    tp.markeer_getekend(sd, meta["doc_id"], "a@x.nl", "1.1.1.1", "UA", "Eerste Naam", payload)
    tp.markeer_getekend(sd, meta["doc_id"], "a@x.nl", "2.2.2.2", "UA", "Tweede Naam", payload)
    meta = tp.lees_meta(sd, meta["doc_id"])
    o = next(o for o in meta["ondertekenaars"] if o["email"] == "a@x.nl")
    assert o["getekende_naam"] == "Eerste Naam"  # eerste registratie blijft
    assert o["ip_adres"] == "1.1.1.1"


def test_genereer_vereist_iedereen_getekend(tmp_path):
    sd = str(tmp_path)
    meta = _tot_en_met_verzonden(sd)
    tp.markeer_getekend(sd, meta["doc_id"], "a@x.nl", "1.1.1.1", "UA", "Alice", _mini_handtekening_payload())
    with pytest.raises(ValueError):
        tp.genereer_getekend_pdf(sd, meta["doc_id"])  # b@y.nl nog niet getekend


def test_lijst_documenten_nieuwste_eerst(tmp_path):
    sd = str(tmp_path)
    a = tp.maak_document(sd, "Eerste", _mini_pdf(1), "a.pdf", "jurian")
    a["aangemaakt_op"] = "2026-01-01T10:00:00"
    tp._schrijf_meta(sd, a)
    b = tp.maak_document(sd, "Tweede", _mini_pdf(1), "b.pdf", "jurian")
    b["aangemaakt_op"] = "2026-02-01T10:00:00"
    tp._schrijf_meta(sd, b)
    titels = [m["titel"] for m in tp.lijst_documenten(sd)]
    assert titels[0] == "Tweede"


def test_zoek_via_onbekende_token(tmp_path):
    assert tp.zoek_via_token(str(tmp_path), "bestaat-niet") is None


def test_tekstveld_moet_tekst_hebben(tmp_path):
    meta = tp.maak_document(str(tmp_path), "T", _mini_pdf(1), "c.pdf", "jurian")
    with pytest.raises(ValueError):
        tp.zet_velden(str(tmp_path), meta["doc_id"], [{"type": "tekst", "pagina": 0, "x": 0.1, "y": 0.1}])


def test_alleen_tekstvelden_kan_niet_verstuurd_worden(tmp_path):
    meta = tp.maak_document(str(tmp_path), "T", _mini_pdf(1), "c.pdf", "jurian")
    tp.zet_velden(str(tmp_path), meta["doc_id"], [
        {"type": "tekst", "pagina": 0, "x": 0.1, "y": 0.1, "tekst": "Haarlem"},
    ])
    with pytest.raises(ValueError):
        tp.bereid_verzending_voor(str(tmp_path), meta["doc_id"])


def test_tekstveld_telt_niet_als_ondertekenaar(tmp_path):
    meta = tp.maak_document(str(tmp_path), "T", _mini_pdf(1), "c.pdf", "jurian")
    meta = tp.zet_velden(str(tmp_path), meta["doc_id"], [
        {"type": "handtekening", "pagina": 0, "x": 0.1, "y": 0.8, "email": "a@x.nl", "naam": "Alice"},
        {"type": "tekst", "pagina": 0, "x": 0.1, "y": 0.1, "tekst": "Haarlem"},
    ])
    assert [o["email"] for o in tp.unieke_ondertekenaars(meta)] == ["a@x.nl"]
    assert len(tp.tekstvelden(meta)) == 1


def test_tekstveld_wordt_op_pdf_gestempeld(tmp_path):
    sd = str(tmp_path)
    meta = tp.maak_document(sd, "Contract", _mini_pdf(1), "c.pdf", "jurian")
    tp.zet_velden(sd, meta["doc_id"], [
        {"type": "handtekening", "pagina": 0, "x": 0.1, "y": 0.8, "email": "a@x.nl", "naam": "Alice"},
        {"type": "tekst", "pagina": 0, "x": 0.1, "y": 0.2, "breedte": 0.3, "hoogte": 0.04, "tekst": "Haarlem"},
    ])
    meta = tp.bereid_verzending_voor(sd, meta["doc_id"])
    tp.markeer_getekend(sd, meta["doc_id"], "a@x.nl", "1.2.3.4", "UA", "Alice Jansen", _mini_handtekening_payload())
    _naam, out = tp.genereer_getekend_pdf(sd, meta["doc_id"])
    chk = fitz.open(stream=out, filetype="pdf")
    pagina0_tekst = chk[0].get_text()
    chk.close()
    assert "Haarlem" in pagina0_tekst  # ingevulde tekst staat op de originele pagina


def test_drive_upload_zonder_remote_faalt_stil():
    cfg = SimpleNamespace(rclone_remote=None)
    assert drive_sync.upload_getekend_document(cfg, "x.pdf", b"data") is False

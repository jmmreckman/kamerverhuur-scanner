"""Los tekenportaal: zelf een PDF uploaden, zelf aanwijzen waar handtekeningen
moeten komen, en per plek een mailadres koppelen met een tekenverzoek. Niet
pand-gebonden (los menu-item). De bestaande, pand-specifieke huurcontract-
ondertekening (webapp/ondertekenen.py) blijft hier volledig los van en intact.

Elke ondertekenaar (uniek mailadres) krijgt een eigen, niet te raden link
(/document-tekenen/<token>) en tekent met een canvas-handtekening. Per
ondertekening leggen we een audit-trail vast: getekende naam, tijdstip, IP-adres,
user-agent en de getekende handtekening (base64-PNG). Dit is een gewone
elektronische handtekening (SES onder eIDAS) - mits goed gedocumenteerd, zoals
hier, rechtsgeldig voor dit soort documenten.

Zodra iedereen getekend heeft, stempelen we elke handtekening op de aangewezen
plek in de PDF en voegen we een officiele ondertekeningsverklaring (certificaat-/
audit-pagina) toe, inclusief de SHA-256 van het originele document. Het resultaat
gaat naar de Drive-map "Steenhub getekende documenten" en wordt naar alle
partijen gemaild.

Opslag (naast state.json):
    <state_dir>/tekenportaal/<doc_id>/origineel.pdf
    <state_dir>/tekenportaal/<doc_id>/meta.json
    <state_dir>/tekenportaal/<doc_id>/getekend.pdf   (zodra afgerond)
    <state_dir>/tekenportaal/tokens.json             (token -> doc_id)
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from datetime import datetime
from pathlib import Path

import fitz  # pymupdf

from .handtekening import handtekening_base64_uit_data_url

MAX_PDF_BYTES = 25 * 1024 * 1024  # 25 MB - ruim voor contracten/offertes

# Standaard veldafmeting (genormaliseerd t.o.v. paginabreedte/-hoogte) als de UI
# er geen meegeeft.
STD_BREEDTE = 0.26
STD_HOOGTE = 0.07

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def geldig_email(waarde: str) -> bool:
    return bool(_EMAIL_RE.match((waarde or "").strip()))


# ---------------------------------------------------------------- opslagpaden

def _root(state_dir: str) -> Path:
    return Path(state_dir) / "tekenportaal"


def _doc_dir(state_dir: str, doc_id: str) -> Path:
    # doc_id is altijd een door ons gegenereerde hex-string; voor de zekerheid
    # weren we toch alles wat geen pad-veilige token is.
    if not re.fullmatch(r"[0-9a-f]{8,}", doc_id or ""):
        raise ValueError("Ongeldig document-id.")
    return _root(state_dir) / doc_id


def _meta_pad(state_dir: str, doc_id: str) -> Path:
    return _doc_dir(state_dir, doc_id) / "meta.json"


def _origineel_pad(state_dir: str, doc_id: str) -> Path:
    return _doc_dir(state_dir, doc_id) / "origineel.pdf"


def _getekend_pad(state_dir: str, doc_id: str) -> Path:
    return _doc_dir(state_dir, doc_id) / "getekend.pdf"


def _tokens_pad(state_dir: str) -> Path:
    return _root(state_dir) / "tokens.json"


# ---------------------------------------------------------------- meta / lijst

def lees_meta(state_dir: str, doc_id: str) -> dict | None:
    pad = _meta_pad(state_dir, doc_id)
    if not pad.is_file():
        return None
    try:
        return json.loads(pad.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _schrijf_meta(state_dir: str, meta: dict) -> None:
    pad = _meta_pad(state_dir, meta["doc_id"])
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def lijst_documenten(state_dir: str) -> list[dict]:
    """Alle documenten, nieuwste eerst."""
    root = _root(state_dir)
    if not root.is_dir():
        return []
    metas = []
    for kind in root.iterdir():
        if kind.is_dir():
            meta = lees_meta(state_dir, kind.name)
            if meta:
                metas.append(meta)
    return sorted(metas, key=lambda m: m.get("aangemaakt_op", ""), reverse=True)


# ---------------------------------------------------------------- aanmaken

def is_geldige_pdf(inhoud: bytes) -> bool:
    try:
        with fitz.open(stream=inhoud, filetype="pdf") as doc:
            return doc.page_count > 0
    except Exception:
        return False


def maak_document(state_dir: str, titel: str, origineel_bytes: bytes,
                  origineel_bestandsnaam: str, aangemaakt_door: str) -> dict:
    """Slaat een geuploade PDF op als nieuw tekendocument (status 'concept')."""
    if not origineel_bytes or len(origineel_bytes) > MAX_PDF_BYTES:
        raise ValueError("Bestand is leeg of te groot (max 25 MB).")
    if not is_geldige_pdf(origineel_bytes):
        raise ValueError("Dit is geen geldig PDF-bestand.")

    doc_id = secrets.token_hex(12)
    _doc_dir(state_dir, doc_id).mkdir(parents=True, exist_ok=True)
    _origineel_pad(state_dir, doc_id).write_bytes(origineel_bytes)

    meta = {
        "doc_id": doc_id,
        "titel": (titel or "").strip() or Path(origineel_bestandsnaam).stem or "Document",
        "origineel_bestandsnaam": Path(origineel_bestandsnaam).name or "document.pdf",
        "origineel_sha256": document_sha256(origineel_bytes),
        "aangemaakt_op": datetime.now().isoformat(timespec="seconds"),
        "aangemaakt_door": aangemaakt_door,
        "status": "concept",        # concept -> verzonden -> afgerond
        "velden": [],
        "ondertekenaars": [],
        "verzonden_op": None,
        "afgerond_op": None,
        "getekend_bestandsnaam": None,
    }
    _schrijf_meta(state_dir, meta)
    return meta


# ---------------------------------------------------------------- pagina's renderen

def pagina_aantal(state_dir: str, doc_id: str) -> int:
    with fitz.open(_origineel_pad(state_dir, doc_id)) as doc:
        return doc.page_count


def render_pagina_png(state_dir: str, doc_id: str, pagina: int, zoom: float = 2.0) -> bytes:
    """Rendert een pagina van de originele PDF als PNG - voor het plaatsen van
    velden en voor de voorvertoning op de tekenpagina."""
    with fitz.open(_origineel_pad(state_dir, doc_id)) as doc:
        if pagina < 0 or pagina >= doc.page_count:
            raise ValueError("Pagina bestaat niet.")
        page = doc[pagina]
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("png")


# ---------------------------------------------------------------- velden

def _clamp(waarde: float, onder: float = 0.0, boven: float = 1.0) -> float:
    try:
        f = float(waarde)
    except (TypeError, ValueError):
        return onder
    return max(onder, min(boven, f))


def is_tekstveld(veld: dict) -> bool:
    return veld.get("type") == "tekst"


def zet_velden(state_dir: str, doc_id: str, velden: list[dict]) -> dict:
    """Vervangt de velden van een document (alleen toegestaan zolang het nog
    'concept' is, dus voor het versturen). Twee soorten:
    - type 'handtekening': een geldig mailadres (+ optioneel naam); daar tekent
      de gekoppelde ondertekenaar.
    - type 'tekst': een door jou ingevulde tekst (plaats, BSN, datum, ...) die
      bij het afronden op de PDF wordt gezet.
    Elk veld heeft pagina (int) en x, y, breedte, hoogte (genormaliseerd 0..1)."""
    meta = lees_meta(state_dir, doc_id)
    if meta is None:
        raise ValueError("Document niet gevonden.")
    if meta["status"] != "concept":
        raise ValueError("Velden kunnen alleen aangepast worden voordat het verzoek verstuurd is.")

    aantal_paginas = pagina_aantal(state_dir, doc_id)
    schoon: list[dict] = []
    for rauw in velden:
        soort = (rauw.get("type") or "handtekening").strip()
        if soort not in ("handtekening", "tekst"):
            soort = "handtekening"
        try:
            pagina = int(rauw.get("pagina", 0))
        except (TypeError, ValueError):
            pagina = 0
        if pagina < 0 or pagina >= aantal_paginas:
            raise ValueError("Een veld verwijst naar een niet-bestaande pagina.")

        veld = {
            "veld_id": secrets.token_hex(6),
            "type": soort,
            "pagina": pagina,
            "x": _clamp(rauw.get("x", 0)),
            "y": _clamp(rauw.get("y", 0)),
            "breedte": _clamp(rauw.get("breedte", STD_BREEDTE), 0.02, 1.0),
            "hoogte": _clamp(rauw.get("hoogte", STD_HOOGTE), 0.015, 1.0),
            "email": "",
            "naam": "",
            "tekst": "",
        }
        if soort == "tekst":
            tekst = (rauw.get("tekst") or "").strip()
            if not tekst:
                raise ValueError("Een tekstveld is leeg - vul tekst in of verwijder het veld.")
            veld["tekst"] = tekst
        else:
            email = (rauw.get("email") or "").strip()
            if not geldig_email(email):
                raise ValueError(f"Ongeldig mailadres bij een handtekeningveld: {email or '(leeg)'}")
            veld["email"] = email
            veld["naam"] = (rauw.get("naam") or "").strip()
        schoon.append(veld)

    if not schoon:
        raise ValueError("Plaats minstens één veld voordat je opslaat.")

    meta["velden"] = schoon
    _schrijf_meta(state_dir, meta)
    return meta


def unieke_ondertekenaars(meta: dict) -> list[dict]:
    """De unieke mailadressen uit de handtekeningvelden, met (eerste niet-lege)
    naam - in volgorde van voorkomen. Tekstvelden tellen niet mee."""
    gezien: dict[str, str] = {}
    for veld in meta.get("velden", []):
        if is_tekstveld(veld):
            continue
        email = veld["email"]
        if email not in gezien:
            gezien[email] = veld.get("naam", "")
        elif not gezien[email] and veld.get("naam"):
            gezien[email] = veld["naam"]
    return [{"email": e, "naam": n} for e, n in gezien.items()]


# ---------------------------------------------------------------- verzenden / tokens

def _lees_tokens(state_dir: str) -> dict:
    pad = _tokens_pad(state_dir)
    if not pad.is_file():
        return {}
    try:
        return json.loads(pad.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _schrijf_tokens(state_dir: str, index: dict) -> None:
    pad = _tokens_pad(state_dir)
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text(json.dumps(index), encoding="utf-8")


def bereid_verzending_voor(state_dir: str, doc_id: str) -> dict:
    """Maakt per uniek mailadres een ondertekenaar met eigen token aan en zet het
    document op 'verzonden'. Idempotent: een al verzonden document houdt z'n
    bestaande tokens/ondertekenaars (zodat verstuurde links geldig blijven)."""
    meta = lees_meta(state_dir, doc_id)
    if meta is None:
        raise ValueError("Document niet gevonden.")
    if meta["status"] != "concept":
        return meta
    if not any(not is_tekstveld(v) for v in meta.get("velden", [])):
        raise ValueError("Plaats eerst minstens één handtekeningveld (alleen tekstvelden kan niet verstuurd worden).")

    ondertekenaars = []
    index = _lees_tokens(state_dir)
    for deelnemer in unieke_ondertekenaars(meta):
        token = secrets.token_urlsafe(32)
        ondertekenaars.append({
            "email": deelnemer["email"],
            "naam": deelnemer["naam"],
            "token": token,
            "ondertekend_op": None,
            "ip_adres": None,
            "user_agent": None,
            "getekende_naam": None,
            "handtekening_png_base64": None,
        })
        index[token] = doc_id
    _schrijf_tokens(state_dir, index)

    meta["ondertekenaars"] = ondertekenaars
    meta["status"] = "verzonden"
    meta["verzonden_op"] = datetime.now().isoformat(timespec="seconds")
    _schrijf_meta(state_dir, meta)
    return meta


def zoek_via_token(state_dir: str, token: str) -> tuple[dict, dict] | None:
    """(meta, ondertekenaar) voor deze token, of None als onbekend."""
    doc_id = _lees_tokens(state_dir).get(token)
    if not doc_id:
        return None
    meta = lees_meta(state_dir, doc_id)
    if meta is None:
        return None
    for ondertekenaar in meta.get("ondertekenaars", []):
        if ondertekenaar["token"] == token:
            return meta, ondertekenaar
    return None


def velden_voor_email(meta: dict, email: str) -> list[dict]:
    return [v for v in meta.get("velden", []) if not is_tekstveld(v) and v["email"] == email]


def tekstvelden(meta: dict) -> list[dict]:
    return [v for v in meta.get("velden", []) if is_tekstveld(v)]


def markeer_getekend(state_dir: str, doc_id: str, email: str, ip_adres: str,
                     user_agent: str, getekende_naam: str,
                     handtekening_png_base64: str | None) -> dict:
    """Legt de handtekening van één ondertekenaar vast. Idempotent: een al
    getekende ondertekenaar blijft bij de eerste registratie."""
    meta = lees_meta(state_dir, doc_id)
    if meta is None:
        raise ValueError("Document niet gevonden.")
    for ondertekenaar in meta.get("ondertekenaars", []):
        if ondertekenaar["email"] == email and ondertekenaar["ondertekend_op"] is None:
            ondertekenaar["ondertekend_op"] = datetime.now().isoformat(timespec="seconds")
            ondertekenaar["ip_adres"] = ip_adres
            ondertekenaar["user_agent"] = (user_agent or "")[:400]
            ondertekenaar["getekende_naam"] = getekende_naam
            ondertekenaar["handtekening_png_base64"] = handtekening_png_base64
            break
    _schrijf_meta(state_dir, meta)
    return meta


def alles_getekend(meta: dict) -> bool:
    ondertekenaars = meta.get("ondertekenaars", [])
    return bool(ondertekenaars) and all(o["ondertekend_op"] for o in ondertekenaars)


# ---------------------------------------------------------------- getekende PDF

def document_sha256(inhoud: bytes) -> str:
    return hashlib.sha256(inhoud).hexdigest()


def _veilige_bestandsnaam(titel: str) -> str:
    kaal = re.sub(r"[^0-9A-Za-z._ -]", "", (titel or "Document")).strip() or "Document"
    kaal = re.sub(r"\s+", " ", kaal)
    return f"{kaal} - getekend.pdf"


def _ondertekenaar_voor_email(meta: dict, email: str) -> dict | None:
    for o in meta.get("ondertekenaars", []):
        if o["email"] == email:
            return o
    return None


def genereer_getekend_pdf(state_dir: str, doc_id: str) -> tuple[str, bytes]:
    """Stempelt alle handtekeningen op hun plek en voegt een
    ondertekeningsverklaring (audit-pagina) toe. Slaat het resultaat op als
    getekend.pdf, werkt de meta bij naar 'afgerond' en geeft (bestandsnaam,
    bytes) terug."""
    meta = lees_meta(state_dir, doc_id)
    if meta is None:
        raise ValueError("Document niet gevonden.")
    if not alles_getekend(meta):
        raise ValueError("Nog niet iedereen heeft getekend.")

    with fitz.open(_origineel_pad(state_dir, doc_id)) as doc:
        # 1) velden op hun aangewezen plek op de PDF zetten
        for veld in meta["velden"]:
            page = doc[veld["pagina"]]
            pr = page.rect
            rect = fitz.Rect(
                pr.x0 + veld["x"] * pr.width,
                pr.y0 + veld["y"] * pr.height,
                pr.x0 + (veld["x"] + veld["breedte"]) * pr.width,
                pr.y0 + (veld["y"] + veld["hoogte"]) * pr.height,
            )
            if is_tekstveld(veld):
                # Ingevulde tekst (plaats, BSN, datum, ...) - lettergrootte schaalt
                # mee met de veldhoogte, met een redelijke onder-/bovengrens.
                fontsize = max(7.0, min(13.0, rect.height * 0.62))
                page.insert_textbox(
                    rect, veld.get("tekst", ""), fontsize=fontsize, fontname="helv",
                    color=(0, 0, 0), align=0,
                )
                continue
            ondertekenaar = _ondertekenaar_voor_email(meta, veld["email"])
            if not ondertekenaar or not ondertekenaar.get("handtekening_png_base64"):
                continue
            try:
                png = base64.b64decode(ondertekenaar["handtekening_png_base64"])
            except Exception:
                continue
            page.insert_image(rect, stream=png, keep_proportion=True, overlay=True)
            # kleine, zakelijke onderschrift-regel onder de handtekening
            naam = ondertekenaar.get("getekende_naam") or ondertekenaar.get("naam") or veld["email"]
            moment = _nl_moment(ondertekenaar.get("ondertekend_op"))
            bijschrift = fitz.Rect(rect.x0, rect.y1, rect.x1, min(pr.y1, rect.y1 + 14))
            page.insert_textbox(
                bijschrift, f"{naam} - {moment}", fontsize=6, fontname="helv",
                color=(0.33, 0.33, 0.33), align=0,
            )

        _voeg_verklaring_toe(doc, meta)
        getekend_bytes = doc.tobytes(deflate=True)

    _getekend_pad(state_dir, doc_id).write_bytes(getekend_bytes)
    bestandsnaam = _veilige_bestandsnaam(meta["titel"])
    meta["status"] = "afgerond"
    meta["afgerond_op"] = datetime.now().isoformat(timespec="seconds")
    meta["getekend_bestandsnaam"] = bestandsnaam
    meta["getekend_sha256"] = document_sha256(getekend_bytes)
    _schrijf_meta(state_dir, meta)
    return bestandsnaam, getekend_bytes


def lees_getekend_pdf(state_dir: str, doc_id: str) -> bytes | None:
    pad = _getekend_pad(state_dir, doc_id)
    return pad.read_bytes() if pad.is_file() else None


def lees_origineel_pdf(state_dir: str, doc_id: str) -> bytes | None:
    pad = _origineel_pad(state_dir, doc_id)
    return pad.read_bytes() if pad.is_file() else None


def _nl_moment(iso: str | None) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d-%m-%Y %H:%M")
    except (TypeError, ValueError):
        return ""


def _voeg_verklaring_toe(doc: "fitz.Document", meta: dict) -> None:
    """Voegt een officiele ondertekeningsverklaring/certificaat-pagina toe met de
    audit-gegevens per ondertekenaar en de documenthash."""
    page = doc.new_page(width=595, height=842)  # A4
    marge = 50
    breedte = 595 - 2 * marge
    donker = (0.1, 0.1, 0.1)
    grijs = (0.4, 0.4, 0.4)

    page.insert_text((marge, 70), "Ondertekeningsverklaring", fontname="hebo",
                     fontsize=18, color=donker)
    page.insert_text((marge, 88), "Signature certificate", fontname="helv",
                     fontsize=10, color=grijs)
    page.draw_line((marge, 100), (595 - marge, 100), color=(0.8, 0.8, 0.8), width=0.8)

    intro = (
        f'Document: "{meta["titel"]}" ({meta["origineel_bestandsnaam"]})\n'
        f'Aangemaakt op: {_nl_moment(meta.get("aangemaakt_op"))} door {meta.get("aangemaakt_door", "")}\n'
        f'SHA-256 van het originele document: {meta.get("origineel_sha256", "")}\n\n'
        "De onderstaande partijen hebben dit document elektronisch ondertekend. Dit betreft een "
        "gewone elektronische handtekening (SES) in de zin van de eIDAS-verordening. Per "
        "ondertekening zijn de getypte naam, datum en tijd, het IP-adres en de browser-"
        "identificatie (user-agent) vastgelegd als bewijs."
    )
    rect = fitz.Rect(marge, 112, 595 - marge, 230)
    page.insert_textbox(rect, intro, fontsize=9, fontname="helv", color=donker, align=0)

    y = 240
    for i, o in enumerate(meta.get("ondertekenaars", []), start=1):
        if y > 720:  # nieuwe pagina als het blok niet meer past
            page = doc.new_page(width=595, height=842)
            y = 70
        page.draw_line((marge, y), (595 - marge, y), color=(0.85, 0.85, 0.85), width=0.6)
        y += 14
        naam = o.get("getekende_naam") or o.get("naam") or ""
        page.insert_text((marge, y), f"{i}. {naam}", fontname="hebo", fontsize=11, color=donker)
        y += 16
        regels = [
            f"E-mailadres: {o.get('email', '')}",
            f"Getypte naam: {o.get('getekende_naam', '')}",
            f"Ondertekend op: {_nl_moment(o.get('ondertekend_op'))}",
            f"IP-adres: {o.get('ip_adres') or ''}",
            f"User-agent: {(o.get('user_agent') or '')[:120]}",
        ]
        blok = fitz.Rect(marge, y, marge + breedte - 170, y + 70)
        page.insert_textbox(blok, "\n".join(regels), fontsize=8.5, fontname="helv", color=donker)
        # handtekening-thumbnail rechts
        if o.get("handtekening_png_base64"):
            try:
                png = base64.b64decode(o["handtekening_png_base64"])
                hrect = fitz.Rect(595 - marge - 150, y - 4, 595 - marge, y + 44)
                page.insert_image(hrect, stream=png, keep_proportion=True, overlay=True)
            except Exception:
                pass
        y += 80

"""PDF-export van de rekentool per woning (kansen.steenhub.nl). Zet dezelfde
uitgangspunten en resultaten die op de rekenpagina staan om naar een nette PDF ter
download. reportlab genereert het document in het geheugen (bytes)."""
from __future__ import annotations

import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_GROEN = colors.HexColor("#1b7a43")
_ROOD = colors.HexColor("#c0392b")
_GRIJS = colors.HexColor("#66707a")
_RAND = colors.HexColor("#d8dde3")
_ACHTERGROND = colors.HexColor("#f2f6f3")

# Moet gelijk blijven aan ICR_NORM in rotterdam_scanner/investering.py.
_ICR_NORM = 1.25

# Welke resultaatvelden zijn een percentage (rest is euro).
_RESULTAAT_PROCENT = {"rendement"}


def _icr(waarde) -> str:
    if waarde is None:
        return "—"
    return f"{waarde:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".") + "×"


def _euro(bedrag) -> str:
    if bedrag is None:
        return "—"
    negatief = bedrag < 0
    tekst = f"{abs(bedrag):,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return ("−" if negatief else "") + "€ " + tekst


def _procent_fractie(fractie) -> str:
    if fractie is None:
        return "—"
    return f"{fractie * 100:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".") + "%"


def _veld_waarde(veld: dict) -> str:
    waarde = veld["waarde"]
    if veld["soort"] == "euro":
        return _euro(waarde)
    if veld["soort"] == "procent":
        # waarde is hier al een heel percentage (bv. 8 of 6,25), niet de fractie.
        return str(waarde).replace(".", ",") + "%"
    return str(int(waarde)) if isinstance(waarde, float) and waarde.is_integer() else str(waarde)


def _tabel(rijen, kolombreedtes, accent_rijen=(), waarde_kleuren=None) -> Table:
    tabel = Table(rijen, colWidths=kolombreedtes, hAlign="LEFT")
    stijl = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1c2126")),
        ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#1c2126")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, _RAND),
        ("BOX", (0, 0), (-1, -1), 0.5, _RAND),
    ]
    for r in accent_rijen:
        stijl.append(("BACKGROUND", (0, r), (-1, r), _ACHTERGROND))
        stijl.append(("FONTNAME", (0, r), (-1, r), "Helvetica-Bold"))
        stijl.append(("TEXTCOLOR", (1, r), (1, r), _GROEN))
    # Specifieke kleuren voor de waardekolom (bv. groen/rood voor de ICR-regels).
    for r, kleur in (waarde_kleuren or {}).items():
        stijl.append(("FONTNAME", (1, r), (1, r), "Helvetica-Bold"))
        stijl.append(("TEXTCOLOR", (1, r), (1, r), kleur))
    tabel.setStyle(TableStyle(stijl))
    return tabel


def bouw_berekening_pdf(item, velden: list[dict], resultaat: dict, vandaag: date | None = None) -> bytes:
    vandaag = vandaag or date.today()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=16 * mm,
        title=f"Rekentool - {item.weergavenaam}", author="kansen.steenhub.nl",
    )
    basis = getSampleStyleSheet()
    titel_stijl = ParagraphStyle("Titel", parent=basis["Title"], textColor=_GROEN, fontSize=18, spaceAfter=2)
    sub_stijl = ParagraphStyle("Sub", parent=basis["Normal"], textColor=_GRIJS, fontSize=10, spaceAfter=2)
    kop_stijl = ParagraphStyle("Kop", parent=basis["Heading2"], textColor=colors.HexColor("#1c2126"),
                               fontSize=12, spaceBefore=14, spaceAfter=6)
    voet_stijl = ParagraphStyle("Voet", parent=basis["Normal"], textColor=_GRIJS, fontSize=8, spaceBefore=16)

    elementen = [Paragraph(f"Rekentool &mdash; {item.weergavenaam}", titel_stijl)]

    subregels = []
    if getattr(item, "wijknaam", None):
        subregels.append(item.wijknaam)
    if getattr(item, "primaire_oppervlakte", None):
        subregels.append(f"{item.primaire_oppervlakte} m&sup2;")
    if getattr(item, "prijs", None):
        subregels.append(f"vraagprijs {_euro(item.prijs)}")
    if subregels:
        elementen.append(Paragraph(" &middot; ".join(subregels), sub_stijl))
    if getattr(item, "url", None):
        elementen.append(Paragraph(f'<a href="{item.url}">{item.url}</a>', sub_stijl))

    breedte = doc.width
    kolommen = [breedte * 0.62, breedte * 0.38]

    # Uitgangspunten
    elementen.append(Paragraph("Uitgangspunten", kop_stijl))
    rijen = [[v["label"], _veld_waarde(v)] for v in velden]
    elementen.append(_tabel(rijen, kolommen))

    # Belangrijke resultaten
    elementen.append(Paragraph("Belangrijke resultaten", kop_stijl))
    belangrijk = [
        ("Winst per maand p.p.", "winst_pm_pp"),
        ("Eigen inleg vóór ophoging (totaal)", "eigen_inleg_voor_ophoging_totaal"),
        ("Eigen inleg ná ophoging (p.p.)", "eigen_inleg_na_ophoging_pp"),
    ]
    rijen = [[label, _procent_fractie(resultaat.get(key)) if key in _RESULTAAT_PROCENT else _euro(resultaat.get(key))]
             for label, key in belangrijk]
    elementen.append(_tabel(rijen, kolommen, accent_rijen=(0, 2)))

    # Berekende uitgangspunten
    elementen.append(Paragraph("Berekende uitgangspunten", kop_stijl))
    berekend = [
        ("Taxatie vóór vergunning", "taxatie_voor_vergunning"),
        ("Taxatie ná vergunning", "taxatie_na_vergunning"),
        ("Kale WWSO huur kamerverhuur", "kale_huur_pm"),
        ("Kale WWSZ huur aan gezin", "wwsz_huur_gezin"),
        ("Service IN per maand", "service_in_pm"),
        ("Vast UIT per maand", "vast_uit_pm"),
        ("Overdrachtsbelasting", "overdrachtsbelasting_eur"),
        ("Leenbaar vóór verhoging", "leenbaar_voor_verhoging"),
        ("Leenbaar ná verhoging", "leenbaar_na_verhoging"),
        ("Zelf in te leggen bij aankoop", "zelf_in_te_leggen_bij_aankoop"),
        ("Maandelijkse rente ná verhoging", "rente_pm_na_verhoging"),
        ("3 maanden rente leegstand", "leegstand_3mnd"),
        ("Totale zelf in te leggen kosten", "totale_zelf_in_te_leggen"),
        ("Ná vergunning verhoogbaar met", "verhoogbaar_met"),
        ("Financieringslasten tijdens verbouwing", "financieringslasten_verbouwing"),
        ("In te brengen bij passeren", "in_te_brengen_bij_passeren"),
        ("Opname liquiditeit na verbouwing", "opname_liquiditeit_na_verbouwing"),
        ("Aan te tonen eigen middelen", "aan_te_tonen_middelen"),
    ]
    rijen = [[label, _euro(resultaat.get(key))] for label, key in berekend]
    # ICR-regels onderaan, met een euro-waarde los: groen vanaf de norm, anders rood.
    icr_rijen = [
        ("ICR vóór ophoging (woninghuur)", "icr_voor_ophoging"),
        ("ICR ná ophoging (volle huur)", "icr_na_ophoging"),
    ]
    waarde_kleuren = {}
    for label, key in icr_rijen:
        waarde = resultaat.get(key)
        waarde_kleuren[len(rijen)] = (
            _GROEN if (waarde is not None and waarde >= _ICR_NORM) else _ROOD
        )
        rijen.append([label, _icr(waarde)])
    elementen.append(_tabel(rijen, kolommen, waarde_kleuren=waarde_kleuren))

    elementen.append(Paragraph(
        f"Gegenereerd op {vandaag.strftime('%d-%m-%Y')} via kansen.steenhub.nl. "
        f"Dit is een berekening op basis van aannames, geen taxatie of financieringsadvies.",
        voet_stijl,
    ))

    doc.build(elementen)
    return buffer.getvalue()

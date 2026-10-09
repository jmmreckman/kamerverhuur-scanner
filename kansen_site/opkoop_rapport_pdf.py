"""PDF-rapport van de concurrentie-scan (kansen.steenhub.nl). Zet een
opkoop_scan.ScanResultaat om naar een net, overzichtelijk PDF dat als bijlage wordt
gemaild - zodat de e-mail zelf kort blijft. reportlab bouwt het in het geheugen (bytes)."""
from __future__ import annotations

import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from rotterdam_scanner.opkoop_scan import ScanResultaat

_GROEN = colors.HexColor("#1b7a43")
_ROOD = colors.HexColor("#c0392b")
_GRIJS = colors.HexColor("#66707a")
_RAND = colors.HexColor("#d8dde3")
_ACHTERGROND = colors.HexColor("#f2f6f3")
_DONKER = colors.HexColor("#1c2126")


def _eur(bedrag: int | None) -> str:
    if bedrag is None:
        return "—"
    return "€ " + format(int(bedrag), ",d").replace(",", ".")


def _m2(waarde: int | None) -> str:
    return f"{waarde} m²" if waarde is not None else "—"


def _cel_stijl():
    return ParagraphStyle("Cel", fontName="Helvetica", fontSize=8.5, leading=11,
                          textColor=_DONKER)


def _adreslijst_tabel(breedte, rijen, *, met_woz, met_tekoop, celstijl):
    """Tabel met één rij per adres. Lange lijsten splitsen automatisch over pagina's;
    de koprij wordt bovenaan elke pagina herhaald (repeatRows=1)."""
    koppen = ["Adres", "Afstand"]
    if met_woz:
        koppen.append("WOZ")
    koppen.append("BAG m²")
    if met_tekoop:
        koppen.append("Te koop gezien")

    data = [koppen]
    for a in sorted(rijen, key=lambda x: x.afstand_m):
        rij = [Paragraph(a.weergavenaam, celstijl), f"{a.afstand_m:.0f} m"]
        if met_woz:
            rij.append(_eur(a.woz))
        rij.append(_m2(a.bag_m2))
        if met_tekoop:
            rij.append(a.te_koop_laatst or "—")
        data.append(rij)

    # Kolombreedtes: adres krijgt de ruimte, de rest vaste smalle kolommen.
    vast = [22 * mm]                       # afstand
    if met_woz:
        vast.append(26 * mm)               # WOZ
    vast.append(22 * mm)                   # BAG m²
    if met_tekoop:
        vast.append(30 * mm)               # te koop
    adres_breedte = breedte - sum(vast)
    kolommen = [adres_breedte] + vast

    tabel = Table(data, colWidths=kolommen, hAlign="LEFT", repeatRows=1)
    tabel.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("BACKGROUND", (0, 0), (-1, 0), _ACHTERGROND),
        ("TEXTCOLOR", (0, 0), (-1, -1), _DONKER),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, _RAND),
        ("BOX", (0, 0), (-1, -1), 0.5, _RAND),
    ]))
    return tabel


def bouw_rapport_pdf(r: ScanResultaat, vandaag: date | None = None) -> bytes:
    vandaag = vandaag or date.today()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=15 * mm,
        title=f"Concurrentie-scan - {r.centrum_adres}", author="kansen.steenhub.nl",
    )
    basis = getSampleStyleSheet()
    titel_stijl = ParagraphStyle("Titel", parent=basis["Title"], textColor=_GROEN, fontSize=17, spaceAfter=2)
    sub_stijl = ParagraphStyle("Sub", parent=basis["Normal"], textColor=_GRIJS, fontSize=9.5, spaceAfter=2)
    kop_stijl = ParagraphStyle("Kop", parent=basis["Heading2"], textColor=_DONKER, fontSize=12, spaceBefore=14, spaceAfter=6)
    tekst_stijl = ParagraphStyle("Tekst", parent=basis["Normal"], textColor=_DONKER, fontSize=9.5, spaceAfter=4)
    waarschuw_stijl = ParagraphStyle("Waarschuw", parent=basis["Normal"], textColor=_ROOD, fontSize=9.5, spaceAfter=4)
    voet_stijl = ParagraphStyle("Voet", parent=basis["Normal"], textColor=_GRIJS, fontSize=8, spaceBefore=14)
    celstijl = _cel_stijl()

    breedte = doc.width
    el = [Paragraph(f"Concurrentie-scan &mdash; {r.centrum_adres}", titel_stijl)]
    el.append(Paragraph(
        f"Straal {r.straal_m:.0f} m &middot; WOZ-grens opkoop {_eur(r.grens)} &middot; "
        f"m&sup2;-grens 4 kamers {r.m2_grens} m&sup2; &middot; buurt: {r.buurtnaam or '—'}",
        sub_stijl,
    ))

    if r.woz_onbereikbaar:
        el.append(Paragraph("Let op: de WOZ-dienst was niet bereikbaar; de opkoopbescherming-stap "
                            "kon niet betrouwbaar draaien.", waarschuw_stijl))
    if r.gis_onbereikbaar:
        el.append(Paragraph("Let op: de Rotterdamse vergunningenkaart was niet bereikbaar; de "
                            "50 m-norm-stap kon niet draaien.", waarschuw_stijl))

    # --- Trechter (samenvatting) ---
    el.append(Paragraph("Trechter", kop_stijl))
    opkoop_tekst = (
        f"{len(r.afgevallen_opkoop)} (WOZ ≤ {_eur(r.grens)})"
        if r.in_opkoopwijk else "n.v.t. (geen opkoopbescherming-wijk)"
    )
    samenvatting = [
        ["1. Adressen binnen 50 m", str(len(r.rijen))],
        ["2. Afgevallen - opkoopbescherming", opkoop_tekst],
        ["3. Afgevallen - binnen 50 m van bestaande vergunning", str(len(r.afgevallen_50m))],
        ["Overgebleven pool", str(len(r.pool))],
    ]
    tab = Table(samenvatting, colWidths=[breedte * 0.72, breedte * 0.28], hAlign="LEFT")
    tab.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, _RAND), ("BOX", (0, 0), (-1, -1), 0.5, _RAND),
        ("BACKGROUND", (0, 3), (-1, 3), _ACHTERGROND),
        ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"),
        ("TEXTCOLOR", (1, 3), (1, 3), _GROEN),
    ]))
    el.append(tab)
    el.append(Spacer(1, 2 * mm))
    el.append(Paragraph(
        f"<b>{len(r.pool)}</b> adres(sen) komen - volgens de regels - theoretisch nog in "
        "aanmerking voor een 4+-vergunning. Dit is de reële concurrentiepool.", tekst_stijl))

    # --- Pool ---
    el.append(Paragraph(f"Pool - overgebleven adressen ({len(r.pool)})", kop_stijl))
    if r.pool:
        el.append(_adreslijst_tabel(breedte, r.pool, met_woz=r.in_opkoopwijk,
                                    met_tekoop=r.archief_doorzocht, celstijl=celstijl))
        # Vermeldingen (sluiten niet uit)
        regels = [
            f"Krap voor 4 kamers (BAG &lt; {r.m2_grens} m&sup2;): <b>{len(r.pool_te_klein)}</b> "
            "&ndash; niet uitgesloten; na een dakkapel/aanbouw kan dit veranderen."
        ]
        if r.archief_doorzocht:
            regels.append(f"Afgelopen 12 mnd te koop geweest (voor zover in ons archief): "
                          f"<b>{len(r.pool_te_koop_geweest)}</b>.")
        else:
            regels.append("Te-koop-geweest: het archief wordt nog opgebouwd en is deze keer "
                          "niet meegenomen.")
        el.append(Spacer(1, 2 * mm))
        for reg in regels:
            el.append(Paragraph("&bull; " + reg, tekst_stijl))
    else:
        el.append(Paragraph("Geen adressen overgebleven in de pool.", tekst_stijl))

    # --- Afvallers ---
    if r.afgevallen_opkoop:
        el.append(Paragraph(f"Afgevallen - opkoopbescherming ({len(r.afgevallen_opkoop)})", kop_stijl))
        el.append(_adreslijst_tabel(breedte, r.afgevallen_opkoop, met_woz=True,
                                    met_tekoop=False, celstijl=celstijl))
    if r.afgevallen_50m:
        el.append(Paragraph(f"Afgevallen - binnen 50 m van bestaande vergunning ({len(r.afgevallen_50m)})", kop_stijl))
        el.append(_adreslijst_tabel(breedte, r.afgevallen_50m, met_woz=r.in_opkoopwijk,
                                    met_tekoop=False, celstijl=celstijl))

    el.append(Paragraph(
        "Kanttekening: lopende, nog niet verwerkte aanvragen (doorlooptijd ~14 weken) zijn "
        "niet zichtbaar &ndash; Rotterdam publiceert kamerverhuur-aanvragen niet, alleen de "
        "beslissing.<br/>"
        f"Gegenereerd op {vandaag.strftime('%d-%m-%Y')} via kansen.steenhub.nl. Bron: PDOK "
        "(adressen/coördinaten), WOZ-waardeloket, BAG (oppervlakte), officiële Rotterdamse "
        "vergunningenkaart (50 m-norm).", voet_stijl))

    doc.build(el)
    return buffer.getvalue()

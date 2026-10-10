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


def _adreslijst_tabel(breedte, rijen, *, met_woz, met_tekoop, celstijl,
                      met_gebruiksdoel=False):
    """Tabel met één rij per adres. Lange lijsten splitsen automatisch over pagina's;
    de koprij wordt bovenaan elke pagina herhaald (repeatRows=1)."""
    koppen = ["Adres", "Afstand"]
    if met_woz:
        koppen.append("WOZ")
    koppen.append("BAG m²")
    if met_gebruiksdoel:
        koppen.append("Gebruiksdoel")
    if met_tekoop:
        koppen.append("Te koop gezien")

    data = [koppen]
    for a in sorted(rijen, key=lambda x: x.afstand_m):
        rij = [Paragraph(a.weergavenaam, celstijl), f"{a.afstand_m:.0f} m"]
        if met_woz:
            rij.append(_eur(a.woz))
        rij.append(_m2(a.bag_m2))
        if met_gebruiksdoel:
            rij.append(Paragraph(a.gebruiksdoel or "—", celstijl))
        if met_tekoop:
            rij.append(a.te_koop_laatst or "—")
        data.append(rij)

    # Kolombreedtes: adres krijgt de ruimte, de rest vaste smalle kolommen.
    vast = [22 * mm]                       # afstand
    if met_woz:
        vast.append(26 * mm)               # WOZ
    vast.append(22 * mm)                   # BAG m²
    if met_gebruiksdoel:
        vast.append(34 * mm)               # gebruiksdoel
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


def _risico_blok(breedte, nr, a, adres_stijl, label_stijl, waarde_stijl):
    """Detailblok voor één 'grootste risico'-adres: adres (met link) + een tabel met
    alles wat we weten, voor handmatig onderzoek."""
    from reportlab.platypus import KeepTogether

    naam = a.weergavenaam
    if a.te_koop_url:
        naam = f'<a href="{a.te_koop_url}" color="#1b7a43">{naam}</a>'
    kop = Paragraph(f"{nr}. {naam}", adres_stijl)

    te_koop = a.te_koop_laatst or "—"
    if a.te_koop_sinds and a.te_koop_sinds != a.te_koop_laatst:
        te_koop = f"{a.te_koop_sinds} t/m {a.te_koop_laatst}"
    if (a.te_koop_status or "").lower() == "actief":
        status = "nog actief te koop (volgens laatste gegevens)"
    elif a.te_koop_status:
        status = f"{a.te_koop_status} (≈ daarna van de markt / verkocht rond {a.te_koop_laatst})"
    else:
        status = "—"

    rijen = [
        ["Afstand tot centrum", f"{a.afstand_m:.0f} m"],
        ["WOZ-waarde", _eur(a.woz) if a.woz is not None else "niet openbaar / onbekend"],
        ["Oppervlakte (BAG)", _m2(a.bag_m2)],
        ["Gebruiksdoel", a.gebruiksdoel or "—"],
        ["Te koop gezien", te_koop],
        ["Status (laatst bekend)", status],
        ["Vraagprijs (laatst bekend)", _eur(a.te_koop_prijs) if a.te_koop_prijs else "—"],
        ["Bron", a.te_koop_bron or "—"],
    ]
    data = [[Paragraph(k, label_stijl), Paragraph(str(v), waarde_stijl)] for k, v in rijen]
    tab = Table(data, colWidths=[breedte * 0.34, breedte * 0.66], hAlign="LEFT")
    tab.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, _RAND),
        ("BOX", (0, 0), (-1, -1), 0.5, _RAND),
        ("BACKGROUND", (0, 0), (0, -1), _ACHTERGROND),
    ]))
    return KeepTogether([kop, tab])


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
    risico_kop_stijl = ParagraphStyle("RisicoKop", parent=basis["Heading2"], textColor=_ROOD,
                                      fontSize=13, spaceBefore=14, spaceAfter=4)
    risico_adres_stijl = ParagraphStyle("RisicoAdres", parent=basis["Normal"], textColor=_DONKER,
                                        fontSize=10.5, spaceBefore=8, spaceAfter=3, fontName="Helvetica-Bold")
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
    reeel = r.pool_reeel
    samenvatting = [
        ["1. Adressen binnen 50 m", str(len(r.rijen))],
        ["2. Afgevallen - opkoopbescherming", opkoop_tekst],
        ["3. Afgevallen - binnen 50 m van bestaande vergunning", str(len(r.afgevallen_50m))],
        ["4. Zeer onwaarschijnlijk - ander gebruiksdoel dan wonen", str(len(r.zeer_onwaarschijnlijk))],
        [f"5. Waarschijnlijk geen gevaar - te klein (< {r.m2_grens} m²)", str(len(r.pool_te_klein))],
        ["Reële concurrentiepool", str(len(reeel))],
    ]
    laatste = len(samenvatting) - 1
    tab = Table(samenvatting, colWidths=[breedte * 0.74, breedte * 0.26], hAlign="LEFT")
    tab.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, _RAND), ("BOX", (0, 0), (-1, -1), 0.5, _RAND),
        ("BACKGROUND", (0, laatste), (-1, laatste), _ACHTERGROND),
        ("FONTNAME", (0, laatste), (-1, laatste), "Helvetica-Bold"),
        ("TEXTCOLOR", (1, laatste), (1, laatste), _GROEN),
    ]))
    el.append(tab)
    el.append(Spacer(1, 2 * mm))
    el.append(Paragraph(
        f"<b>{len(reeel)}</b> adres(sen) komen - volgens de regels - theoretisch nog in "
        "aanmerking voor een 4+-vergunning. Dit is de reële concurrentiepool.", tekst_stijl))

    # --- Grootste risico's: reële pool + afgelopen 12 mnd te koop geweest ---
    risicos = r.grootste_risicos
    if risicos:
        label_stijl = ParagraphStyle("RLabel", parent=tekst_stijl, fontName="Helvetica-Bold",
                                     fontSize=9, spaceAfter=0, textColor=_DONKER)
        waarde_stijl = ParagraphStyle("RWaarde", parent=tekst_stijl, fontSize=9, spaceAfter=0)
        el.append(Paragraph(f"⚑ Grootste risico's - handmatig onderzoeken ({len(risicos)})",
                            risico_kop_stijl))
        el.append(Paragraph(
            "Deze adressen zijn <b>én</b> viabel voor een 4+-vergunning (reële pool) <b>én</b> "
            "stonden de afgelopen 12 maanden te koop. Dit zijn je topkandidaten om zelf uit te "
            "zoeken - meest recent te koop bovenaan.", tekst_stijl))
        for i, a in enumerate(risicos, 1):
            el.append(_risico_blok(breedte, i, a, risico_adres_stijl, label_stijl, waarde_stijl))

    # --- Reële pool ---
    el.append(Paragraph(f"Reële concurrentiepool ({len(reeel)})", kop_stijl))
    if reeel:
        el.append(_adreslijst_tabel(breedte, reeel, met_woz=r.in_opkoopwijk,
                                    met_tekoop=r.archief_doorzocht, celstijl=celstijl))
        el.append(Spacer(1, 1.5 * mm))
        if r.archief_doorzocht:
            n = len(r.pool_te_koop_geweest)
            el.append(Paragraph(
                f"&bull; Afgelopen 12 mnd te koop geweest (reële pool): <b>{n}</b>. "
                "Let op: dit dekt alleen woningen die onze eigen scanner heeft gezien; die "
                "historie bouwt nog maar kort op (± 1 maand nu) en groeit elke dag - afwezigheid "
                "betekent dus niet per se dat een woning niet te koop stond.", tekst_stijl))
        else:
            el.append(Paragraph("&bull; Te-koop-geweest: nog geen gegevens beschikbaar "
                                "(de historie wordt opgebouwd).", tekst_stijl))
    else:
        el.append(Paragraph("Geen adressen in de reële concurrentiepool.", tekst_stijl))

    # --- Waarschijnlijk geen gevaar: te klein (check dakkapel) ---
    if r.pool_te_klein:
        el.append(Paragraph(
            f"Waarschijnlijk geen gevaar - te klein voor 4 kamers ({len(r.pool_te_klein)})", kop_stijl))
        el.append(Paragraph(
            f"Gebruiksoppervlakte onder de {r.m2_grens} m&sup2;. <b>Niet uitgesloten:</b> na een "
            "dakkapel of aanbouw kan zo'n woning alsnog aan de maat komen - dus check de "
            "verbouwmogelijkheid.", tekst_stijl))
        el.append(_adreslijst_tabel(breedte, r.pool_te_klein, met_woz=r.in_opkoopwijk,
                                    met_tekoop=False, celstijl=celstijl))

    # --- Zeer onwaarschijnlijk: ander gebruiksdoel ---
    if r.zeer_onwaarschijnlijk:
        el.append(Paragraph(
            f"Zeer onwaarschijnlijk - ander gebruiksdoel dan wonen ({len(r.zeer_onwaarschijnlijk)})", kop_stijl))
        el.append(Paragraph(
            "Volgens de BAG geen woonfunctie (bv. kantoor, winkel, industrie, bijeenkomst). "
            "Kamerverhuur is hier zeer onwaarschijnlijk; deze panden hebben ook geen openbare "
            "WOZ-waarde.", tekst_stijl))
        el.append(_adreslijst_tabel(breedte, r.zeer_onwaarschijnlijk, met_woz=False,
                                    met_tekoop=False, met_gebruiksdoel=True, celstijl=celstijl))

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

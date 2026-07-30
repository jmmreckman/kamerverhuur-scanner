from __future__ import annotations

from datetime import date
from html import escape
from urllib.parse import quote

from .pipeline import RunResult
from .state import ListingState

# Bewust GEEN <style>-blok: veel e-mailclients (o.a. de Gmail-app op mobiel) negeren
# <style> in de <head> geheel of gedeeltelijk, waardoor opmaak wegvalt en de tabel
# door elkaar heen kan gaan lopen. Alle opmaak staat daarom inline op elk element --
# dat is de enige manier die betrouwbaar overal hetzelfde rendert.
_BODY_STYLE = "font-family: Arial, Helvetica, sans-serif; color: #1a1a1a;"
_H1_STYLE = "font-size: 20px;"
_H2_STYLE = "font-size: 16px; margin-top: 28px; border-bottom: 1px solid #ddd; padding-bottom: 4px;"
_TABLE_STYLE = "border-collapse: collapse; width: 100%; margin-top: 8px;"
_TH_STYLE = (
    "text-align: left; padding: 6px 10px; border-bottom: 1px solid #eee; font-size: 14px; "
    "vertical-align: top; background: #f4f4f4; white-space: nowrap;"
)
_TD_STYLE = "text-align: left; padding: 6px 10px; border-bottom: 1px solid #eee; font-size: 14px; vertical-align: top;"
# De "Mogelijke huurprijsopslag"-cel bevat soms een lange, aaneengesloten URL zonder
# afbreekpunten -- zonder begrenzing kan die ene cel de kolombreedte van de hele tabel
# opblazen, waardoor andere cellen visueel niet meer bij hun kop lijken te horen.
_TD_OPSLAG_STYLE = _TD_STYLE + " word-break: break-word; overflow-wrap: anywhere; max-width: 260px;"
_SMALL_STYLE = "color: #666; font-size: 12px;"
_BADGE_NIEUW_STYLE = "display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; background: #d7f0d7; color: #1a5c1a;"
_BADGE_CHECK_STYLE = "display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; background: #fff3cd; color: #7a5c00;"
_ACTIE_STYLE = "display: inline-block; white-space: nowrap;"
_ACTIE_VERWIJDER_STYLE = _ACTIE_STYLE + " color: #a12b2b;"

_VERWIJDER_BODY = (
    "Automatisch gegenereerd -- niet aanpassen. Verstuur deze mail om dit huis uit "
    "de lijst te halen."
)


def _dagen_bekend(item: ListingState, today: date) -> int:
    eerst = date.fromisoformat(item.eerst_gezien)
    return (today - eerst).days


def _euro(bedrag: int | float | None) -> str:
    if bedrag is None:
        return "-"
    teken = "-" if bedrag < 0 else ""
    return f"{teken}€{abs(bedrag):,.0f}".replace(",", ".")


def _verwijder_mailto(scanner_email: str, object_id: str) -> str:
    subject = quote(f"Verwijder {object_id}")
    body = quote(_VERWIJDER_BODY)
    return f"mailto:{scanner_email}?subject={subject}&body={body}"


def _maps_zoeklink(plaatsnaam: str, stad: str = "Rotterdam") -> str:
    # Ook de wijknaam moet al in een eigen link staan: Gmail's adres-auto-linking laat
    # tekst die al in een <a> zit met rust, maar springt anders naar de eerstvolgende
    # ongelinkte tekst (precies wat er met de wijknaam-cel gebeurde, zie report.py-log).
    return f"https://www.google.com/maps/search/{quote(f'{plaatsnaam}, {stad}')}"


def _acties_html(item: ListingState, scanner_email: str) -> str:
    verwijder_url = _verwijder_mailto(scanner_email, item.object_id)
    return (
        f'<span style="{_ACTIE_STYLE}"><a href="{escape(item.url)}">Bekijk advertentie &rarr;</a></span><br>'
        f'<span style="{_ACTIE_VERWIJDER_STYLE}"><a href="{escape(verwijder_url)}">Verwijderen</a></span>'
    )


def _row(item: ListingState, today: date, scanner_email: str) -> str:
    dagen = _dagen_bekend(item, today)
    is_nieuw = dagen == 0
    badges = []
    if is_nieuw:
        badges.append(f'<span style="{_BADGE_NIEUW_STYLE}">nieuw vandaag</span>')
    if item.woz_check_nodig:
        badges.append(f'<span style="{_BADGE_CHECK_STYLE}">check WOZ-waarde</span>')

    opmerking_html = f'<br><span style="{_SMALL_STYLE}">{escape(item.opmerking)}</span>' if item.opmerking else ""
    oppervlakte_tekst = f"{item.primaire_oppervlakte} m²" if item.primaire_oppervlakte else "onbekend"
    bag_oppervlakte_tekst = f"{item.bag_oppervlakte} m² (BAG, ter info)" if item.bag_oppervlakte else "-"
    aantal_kamers_tekst = str(item.aantal_kamers_mogelijk) if item.aantal_kamers_mogelijk is not None else "-"
    prijs_per_m2_tekst = _euro(item.prijs_per_m2) + "/m²" if item.prijs_per_m2 else "-"
    opslag_html = (
        "<br>".join(f'<span style="{_SMALL_STYLE}">{escape(s)}</span>' for s in item.huurprijsopslag_signalen)
        or f'<span style="{_SMALL_STYLE}">geen gevonden</span>'
    )

    # "wijk: " ervoor is geen opmaak-grapje: zonder dat label leest "<adres>\n<wijknaam>"
    # voor Gmail als regel 2 van een adres (straat+huisnr, postcode+plaats \n buurt), en
    # linkt het dat zelf door naar Maps -- inclusief een kapotte lege <td> op de plek waar
    # het de boel splitst, ook als beide teksten al in een eigen link staan. Dat label
    # breekt het patroon zodat Gmail's detectie er niet meer op aanslaat.
    wijk_html = (
        f'wijk: <a href="{escape(_maps_zoeklink(item.wijknaam))}">{escape(item.wijknaam)}</a>'
        if item.wijknaam
        else "-"
    )

    winst_tekst = f"{_euro(item.winst_pm_pp)}/mnd" if item.winst_pm_pp is not None else "-"
    eigen_inleg_tekst = _euro(item.eigen_inleg_pp) if item.eigen_inleg_pp is not None else "-"

    return f"""
    <tr>
      <td style="{_TD_STYLE}"><a href="{escape(item.url)}">{escape(item.weergavenaam)}</a></td>
      <td style="{_TD_STYLE}">{wijk_html}</td>
      <td style="{_TD_STYLE}">{_euro(item.prijs)}</td>
      <td style="{_TD_STYLE}">{oppervlakte_tekst}</td>
      <td style="{_TD_STYLE}">{bag_oppervlakte_tekst}</td>
      <td style="{_TD_STYLE}">{aantal_kamers_tekst}</td>
      <td style="{_TD_STYLE}">{prijs_per_m2_tekst}</td>
      <td style="{_TD_STYLE}">{winst_tekst}</td>
      <td style="{_TD_STYLE}">{eigen_inleg_tekst}</td>
      <td style="{_TD_STYLE}">{dagen} dag{'en' if dagen != 1 else ''}</td>
      <td style="{_TD_STYLE}">{' '.join(badges)}{opmerking_html}</td>
      <td style="{_TD_OPSLAG_STYLE}">{opslag_html}</td>
      <td style="{_TD_STYLE}">{_acties_html(item, scanner_email)}</td>
    </tr>
    """


def _actief_tabel_header() -> str:
    koppen = [
        "Adres", "Wijk", "Vraagprijs", "Oppervlakte", "m² (BAG, ter info)", "Kamers mogelijk", "€/m²",
        "Winst p.p./mnd", "Eigen inleg p.p.", "Dagen bekend", "Nog te checken", "Mogelijke huurprijsopslag", "Acties",
    ]  # fmt: skip
    ths = "".join(f'<th style="{_TH_STYLE}">{kop}</th>' for kop in koppen)
    return f"<tr>{ths}</tr>"


def _den_haag_header() -> str:
    koppen = [
        "Adres", "Wijk", "Vraagprijs", "Oppervlakte", "€/m²", "Max bewoners",
        "Winst p.p./mnd", "Eigen inleg p.p.", "Dagen bekend",
        "Aandachtspunten (zelf natrekken)", "Acties",
    ]  # fmt: skip
    ths = "".join(f'<th style="{_TH_STYLE}">{kop}</th>' for kop in koppen)
    return f"<tr>{ths}</tr>"


def _den_haag_row(item: ListingState, today: date, scanner_email: str) -> str:
    dagen = _dagen_bekend(item, today)
    badges = f'<span style="{_BADGE_NIEUW_STYLE}">nieuw vandaag</span>' if dagen == 0 else ""
    oppervlakte_tekst = f"{item.primaire_oppervlakte} m²" if item.primaire_oppervlakte else "onbekend"
    prijs_per_m2_tekst = _euro(item.prijs_per_m2) + "/m²" if item.prijs_per_m2 else "-"
    max_bewoners_tekst = str(item.aantal_kamers_mogelijk) if item.aantal_kamers_mogelijk is not None else "-"
    winst_tekst = f"{_euro(item.winst_pm_pp)}/mnd" if item.winst_pm_pp is not None else "-"
    eigen_inleg_tekst = _euro(item.eigen_inleg_pp) if item.eigen_inleg_pp is not None else "-"
    signalen_html = (
        "<br>".join(f'<span style="{_SMALL_STYLE}">{escape(s)}</span>' for s in item.check_signalen)
        or f'<span style="{_SMALL_STYLE}">-</span>'
    )
    opmerking_html = f'<br><span style="{_SMALL_STYLE}">{escape(item.opmerking)}</span>' if item.opmerking else ""
    wijk_html = (
        f'wijk: <a href="{escape(_maps_zoeklink(item.wijknaam, "Den Haag"))}">{escape(item.wijknaam)}</a>'
        if item.wijknaam
        else "-"
    )
    return f"""
    <tr>
      <td style="{_TD_STYLE}"><a href="{escape(item.url)}">{escape(item.weergavenaam)}</a>{opmerking_html}</td>
      <td style="{_TD_STYLE}">{wijk_html}</td>
      <td style="{_TD_STYLE}">{_euro(item.prijs)}</td>
      <td style="{_TD_STYLE}">{oppervlakte_tekst}</td>
      <td style="{_TD_STYLE}">{prijs_per_m2_tekst}</td>
      <td style="{_TD_STYLE}">{max_bewoners_tekst}{('<br>' + badges) if badges else ''}</td>
      <td style="{_TD_STYLE}">{winst_tekst}</td>
      <td style="{_TD_STYLE}">{eigen_inleg_tekst}</td>
      <td style="{_TD_STYLE}">{dagen} dag{'en' if dagen != 1 else ''}</td>
      <td style="{_TD_OPSLAG_STYLE}">{signalen_html}</td>
      <td style="{_TD_STYLE}">{_acties_html(item, scanner_email)}</td>
    </tr>
    """


def _afvallen_row(item: ListingState) -> str:
    return f"""
    <tr>
      <td style="{_TD_STYLE}"><a href="{escape(item.url)}">{escape(item.weergavenaam)}</a></td>
      <td style="{_TD_STYLE}">{escape(item.afvalreden or '-')}</td>
    </tr>
    """


def _eenvoudige_header(*koppen: str) -> str:
    ths = "".join(f'<th style="{_TH_STYLE}">{kop}</th>' for kop in koppen)
    return f"<tr>{ths}</tr>"


def build_html_report(result: RunResult, today: date, scanner_email: str, expiry_days: int = 30) -> str:
    nieuw_actief_ids = {item.object_id for item in result.nieuw_actief}
    rotterdam_actief = [item for item in result.alle_actief if item.stad != "den_haag"]
    den_haag_actief = [item for item in result.alle_actief if item.stad == "den_haag"]
    actief_header = _actief_tabel_header()
    nieuwe_kansen_rows = "".join(
        _row(item, today, scanner_email) for item in rotterdam_actief if item.object_id in nieuw_actief_ids
    )
    actieve_rows = "".join(_row(item, today, scanner_email) for item in rotterdam_actief)
    den_haag_rows = "".join(_den_haag_row(item, today, scanner_email) for item in den_haag_actief)
    nieuw_afgevallen_rows = "".join(_afvallen_row(item) for item in result.nieuw_afgevallen)
    handmatig_verwijderd_rows = "".join(_afvallen_row(item) for item in result.handmatig_verwijderd)
    onbekend_rows = "".join(_afvallen_row(item) for item in result.nieuw_onbekend_adres)

    fouten_html = ""
    if result.fouten:
        items = "".join(f"<li>{escape(f)}</li>" for f in result.fouten)
        fouten_html = f"<h2>Let op: fouten tijdens dit run</h2><ul>{items}</ul>"

    return f"""<!doctype html>
<html lang="nl">
<head><meta charset="utf-8"><meta name="format-detection" content="address=no, telephone=no, email=no"></head>
<body style="{_BODY_STYLE}">
  <h1 style="{_H1_STYLE}">Kamerverhuur-scanner Rotterdam &amp; Den Haag — {today.strftime('%d-%m-%Y')}</h1>
  <p style="{_SMALL_STYLE}">
    {len(nieuw_actief_ids)} nieuwe kandidaten vandaag, {len(result.alle_actief)} in totaal nog open
    ({len(rotterdam_actief)} Rotterdam, {len(den_haag_actief)} Den Haag),
    {len(result.nieuw_afgevallen)} vandaag afgevallen op de checks.
  </p>

  {fouten_html}

  <h2 style="{_H2_STYLE}">Rotterdam — nieuwe kansen vandaag ({sum(1 for i in rotterdam_actief if i.object_id in nieuw_actief_ids)})</h2>
  <table style="{_TABLE_STYLE}">
    {actief_header}
    {nieuwe_kansen_rows or f'<tr><td style="{_TD_STYLE}" colspan="13">Geen nieuwe kansen vandaag.</td></tr>'}
  </table>

  <h2 style="{_H2_STYLE}">Rotterdam — openstaande kansen ({len(rotterdam_actief)})</h2>
  <p style="{_SMALL_STYLE}">
    Deze huizen zijn NIET afgevallen op nul-quotumgebied, de 50-meter kamerverhuurvergunning-check of
    (waar van toepassing) de automatische WOZ-check voor opkoopbescherming. Gesorteerd op de laagste
    verwachte eigen inleg per persoon (na ophoging van de financiering, zie hieronder) — de beste kans
    staat bovenaan. "Winst p.p./mnd" en "Eigen inleg p.p." staan op "-" zolang oppervlakte of vraagprijs
    nog onbekend zijn. "Dagen bekend" = dagen sinds dit systeem het huis voor het eerst zag in je
    Funda-alertmail. Een huis verdwijnt vanzelf na {expiry_days} dagen als het niet eerder handmatig
    verwijderd is — er wordt niet automatisch op "verkocht" of "onder bod" gecheckt, dat zie je zelf
    aan hoe lang een huis al op de lijst staat.
    Klik "Verwijderen" om een huis er zelf direct uit te halen (bijv. als het toch niet voldoet).
  </p>
  <table style="{_TABLE_STYLE}">
    {actief_header}
    {actieve_rows or f'<tr><td style="{_TD_STYLE}" colspan="13">Geen openstaande kansen.</td></tr>'}
  </table>

  <h2 style="{_H2_STYLE}">Den Haag — openstaande kansen ({len(den_haag_actief)})</h2>
  <p style="{_SMALL_STYLE}">
    Den Haag heeft een andere regelset dan Rotterdam: een omzettingsvergunning voor kamerbewoning
    kan alleen in wijken die op de Leefbaarometer 'goed'-'uitstekend' scoren (2 laatste metingen), en
    max. aantal bewoners = gebruiksoppervlakte / 18 (harde cap 8). Deze woningen komen door die twee
    harde checks. Winst p.p./mnd en eigen inleg p.p. worden met hetzelfde model als Rotterdam berekend
    (met het max. aantal bewoners als kameraantal, zonder monumentenopslag). De "Aandachtspunten"
    (geluidsisolatie, brandveiligheid, pand-/wijk-quotum, MSW) zijn niet publiek te controleren — die
    moet je zelf bij de gemeente natrekken. Opkoopbescherming/WOZ is voor omzetting geschrapt en dus
    geen belemmering.
  </p>
  <table style="{_TABLE_STYLE}">
    {_den_haag_header()}
    {den_haag_rows or f'<tr><td style="{_TD_STYLE}" colspan="11">Geen openstaande Den Haag-kansen.</td></tr>'}
  </table>

  <h2 style="{_H2_STYLE}">Handmatig verwijderd ({len(result.handmatig_verwijderd)})</h2>
  <table style="{_TABLE_STYLE}">
    {_eenvoudige_header("Adres", "Reden")}
    {handmatig_verwijderd_rows or f'<tr><td style="{_TD_STYLE}" colspan="2">Geen.</td></tr>'}
  </table>

  <h2 style="{_H2_STYLE}">Vandaag afgevallen op de checks ({len(result.nieuw_afgevallen)})</h2>
  <table style="{_TABLE_STYLE}">
    {_eenvoudige_header("Adres", "Reden")}
    {nieuw_afgevallen_rows or f'<tr><td style="{_TD_STYLE}" colspan="2">Geen.</td></tr>'}
  </table>

  <h2 style="{_H2_STYLE}">Kon niet automatisch verwerkt worden ({len(result.nieuw_onbekend_adres)})</h2>
  <p style="{_SMALL_STYLE}">Bekijk deze zelf even handmatig op funda — het adres kon niet automatisch herleid worden.</p>
  <table style="{_TABLE_STYLE}">
    {_eenvoudige_header("Link", "Reden")}
    {onbekend_rows or f'<tr><td style="{_TD_STYLE}" colspan="2">Geen.</td></tr>'}
  </table>

  <p style="{_SMALL_STYLE} margin-top: 32px;">
    Herinnering: de WOZ-waarde wordt normaal automatisch opgehaald (via de WOZ-API) en huizen
    boven de opkoopbeschermingsgrens vallen dan al niet meer af — de badge "check WOZ-waarde"
    verschijnt alleen als dat een keer niet is gelukt (zie eventuele opmerking bij het huis).
    Vraagprijs komt uit de opmaak van je Funda-mail zelf en is daardoor iets kwetsbaarder dan de
    rest — klopt een prijs een keer niet, meld dat dan even. "Verwijderen" opent een kant-en-klare
    e-mail; gewoon versturen (niet aanpassen) en het huis is er de volgende run uit.
  </p>
  <p style="{_SMALL_STYLE}">
    "Mogelijke huurprijsopslag" checkt automatisch op rijksmonument en rijksbeschermd
    stads-/dorpsgezicht (officiële Rijksdienst-data, dat laatste alleen bij bouwjaar vóór 1965) en
    nieuwbouwopslag (BAG-bouwjaar) — deze zijn betrouwbaar maar altijd met "mogelijk" gemarkeerd omdat
    de exacte toepassing van de opslag (bijv. niet ook al een andere monumentenopslag) je zelf moet
    checken. Gemeentelijk monument wordt ook gecheckt, maar op basis van een door een derde
    gepubliceerde lijst uit 2021 — dus minder zeker, altijd verifiëren op
    monumentenregister.rotterdam.nl. Provinciaal monument (ook 15%) wordt niet automatisch gecheckt
    (geen bevraagbare open data beschikbaar, en komt in Rotterdam vrijwel nooit voor) — check dit zelf
    als het voor jouw pand relevant lijkt. "geen gevonden" betekent dus niet dat er zeker geen opslag
    mogelijk is, alleen dat de automatische checks niets vonden. De hoogste gevonden opslag (niet
    gestapeld) telt mee in de "Winst p.p./mnd" en "Eigen inleg p.p."-berekening hieronder.
  </p>
  <p style="{_SMALL_STYLE}">
    "Winst p.p./mnd" en "Eigen inleg p.p." gaan uit van een aanname-model met vaste aannames (BAR
    7,6%, overdrachtsbelasting 8%, rente 5,8%, kosten koper €6.000, verbouwkosten €25.000, kale huur
    €550/kamer) en een tweetraps-financiering: eerst een lening o.b.v. 80% van 87,5% van de koopsom,
    daarna "opgehoogd" naar 80% van de taxatie ná vergunning (o.b.v. de verwachte huurinkomsten) zodra
    die vergunning er is. "Eigen inleg p.p." is dus wat er ná die ophoging definitief zelf ingelegd
    blijft, gedeeld door twee (bij twee investeerders) — een negatief bedrag betekent dat de lening na
    ophoging alle kosten dekt. Puur een rekenmodel op basis van aannames, geen advies — check zelf de
    actuele rente/voorwaarden voordat je hierop een bod uitbrengt.
  </p>
</body>
</html>
"""


def _item_regels(item: ListingState, today: date, scanner_email: str) -> list[str]:
    dagen = _dagen_bekend(item, today)
    extra = []
    if item.woz_check_nodig:
        extra.append("check WOZ-waarde")
    oppervlakte_tekst = f"{item.primaire_oppervlakte} m²" if item.primaire_oppervlakte else "oppervlakte onbekend"
    if item.bag_oppervlakte and item.bag_oppervlakte != item.primaire_oppervlakte:
        oppervlakte_tekst += f" ({item.bag_oppervlakte} m² BAG, ter info)"
    prijs_per_m2_tekst = f"{_euro(item.prijs_per_m2)}/m²" if item.prijs_per_m2 else "€/m² onbekend"
    regels = [
        f"- {item.weergavenaam} ({item.wijknaam or '-'}, {dagen} dagen bekend)",
        f"    bekijk: {item.url}",
        f"    verwijderen: {_verwijder_mailto(scanner_email, item.object_id)}",
        f"    {_euro(item.prijs)}, {oppervlakte_tekst}, {prijs_per_m2_tekst}",
    ]
    if item.aantal_kamers_mogelijk is not None:
        regels.append(f"    kamers mogelijk: {item.aantal_kamers_mogelijk}")
    if item.winst_pm_pp is not None and item.eigen_inleg_pp is not None:
        regels.append(
            f"    winst p.p./mnd: {_euro(item.winst_pm_pp)}, eigen inleg p.p.: {_euro(item.eigen_inleg_pp)}"
        )
    if extra:
        regels.append(f"    nog te checken: {', '.join(extra)}")
    if item.huurprijsopslag_signalen:
        regels.append("    mogelijke huurprijsopslag:")
        for signaal in item.huurprijsopslag_signalen:
            regels.append(f"      - {signaal}")
    if item.opmerking:
        regels.append(f"    let op: {item.opmerking}")
    return regels


def _den_haag_item_regels(item: ListingState, today: date, scanner_email: str) -> list[str]:
    dagen = _dagen_bekend(item, today)
    oppervlakte_tekst = f"{item.primaire_oppervlakte} m²" if item.primaire_oppervlakte else "oppervlakte onbekend"
    prijs_per_m2_tekst = f"{_euro(item.prijs_per_m2)}/m²" if item.prijs_per_m2 else "€/m² onbekend"
    regels = [
        f"- {item.weergavenaam} ({item.wijknaam or '-'}, {dagen} dagen bekend)",
        f"    bekijk: {item.url}",
        f"    verwijderen: {_verwijder_mailto(scanner_email, item.object_id)}",
        f"    {_euro(item.prijs)}, {oppervlakte_tekst}, {prijs_per_m2_tekst}",
    ]
    if item.aantal_kamers_mogelijk is not None:
        regels.append(f"    max bewoners: {item.aantal_kamers_mogelijk}")
    if item.winst_pm_pp is not None and item.eigen_inleg_pp is not None:
        regels.append(
            f"    winst p.p./mnd: {_euro(item.winst_pm_pp)}, eigen inleg p.p.: {_euro(item.eigen_inleg_pp)}"
        )
    if item.check_signalen:
        regels.append("    aandachtspunten (zelf natrekken):")
        for signaal in item.check_signalen:
            regels.append(f"      - {signaal}")
    if item.opmerking:
        regels.append(f"    let op: {item.opmerking}")
    return regels


def build_text_report(result: RunResult, today: date, scanner_email: str) -> str:
    nieuw_actief_ids = {item.object_id for item in result.nieuw_actief}
    rotterdam_actief = [item for item in result.alle_actief if item.stad != "den_haag"]
    den_haag_actief = [item for item in result.alle_actief if item.stad == "den_haag"]
    lines = [f"Kamerverhuur-scanner Rotterdam & Den Haag — {today.strftime('%d-%m-%Y')}", ""]

    if result.fouten:
        lines.append("Let op: fouten tijdens dit run:")
        for fout in result.fouten:
            lines.append(f"- {fout}")
        lines.append("")

    rotterdam_nieuw = [item for item in rotterdam_actief if item.object_id in nieuw_actief_ids]
    lines.append(f"Rotterdam - nieuwe kansen vandaag ({len(rotterdam_nieuw)}):")
    for item in rotterdam_nieuw:
        lines.extend(_item_regels(item, today, scanner_email))
    if not rotterdam_nieuw:
        lines.append("  (geen)")

    lines.append("")
    lines.append(f"Rotterdam - openstaande kansen ({len(rotterdam_actief)}), gesorteerd op laagste eigen inleg p.p.:")
    for item in rotterdam_actief:
        lines.extend(_item_regels(item, today, scanner_email))
    if not rotterdam_actief:
        lines.append("  (geen)")

    lines.append("")
    lines.append(f"Den Haag - openstaande kansen ({len(den_haag_actief)}):")
    for item in den_haag_actief:
        lines.extend(_den_haag_item_regels(item, today, scanner_email))
    if not den_haag_actief:
        lines.append("  (geen)")

    lines.append("")
    lines.append(f"Handmatig verwijderd ({len(result.handmatig_verwijderd)}):")
    for item in result.handmatig_verwijderd:
        lines.append(f"- {item.weergavenaam}: {item.afvalreden} ({item.url})")
    if not result.handmatig_verwijderd:
        lines.append("  (geen)")

    lines.append("")
    lines.append(f"Vandaag afgevallen op de checks ({len(result.nieuw_afgevallen)}):")
    for item in result.nieuw_afgevallen:
        lines.append(f"- {item.weergavenaam}: {item.afvalreden} ({item.url})")
    if not result.nieuw_afgevallen:
        lines.append("  (geen)")

    if result.nieuw_onbekend_adres:
        lines.append("")
        lines.append(f"Kon niet automatisch verwerkt worden ({len(result.nieuw_onbekend_adres)}):")
        for item in result.nieuw_onbekend_adres:
            lines.append(f"- {item.url}: {item.afvalreden}")

    return "\n".join(lines)

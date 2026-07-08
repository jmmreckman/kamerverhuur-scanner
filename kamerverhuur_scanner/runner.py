"""Voert een betaalcontrole uit voor één pand: sheet lezen, bunq-betalingen
ophalen, matchen, en (tenzij dry-run) de sheet + geschiedenis bijwerken en
het resultaat cachen voor de website."""
from __future__ import annotations

import calendar
import dataclasses
import logging
from datetime import date, datetime

from decimal import Decimal

from . import state
from .bunq_client import BunqClient
from .config import Config
from .mailer import MailError, verstuur_email
from .matcher import _bepaal_status, match_tenants_to_payments
from .models import Pand, Payment, Status, Tenant, TenantResult
from .sheet_client import SheetClient

logger = logging.getLogger(__name__)

_MAAND_NAMEN_NL = [
    "januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december",
]
_ALLES_BETAALD_KAMER_SLEUTEL = "__alle_kamers__"
_ALLES_BETAALD_SOORT = "alles-betaald"
_MAAND_NAAM_NAAR_NUMMER = {naam: i + 1 for i, naam in enumerate(_MAAND_NAMEN_NL)}

# Harde grens voor welke kalendermaand een betaling telt: 1e t/m 17e van de
# maand = die maand zelf, 18e t/m einde van de maand = de maand erna (bv. een
# huurder die halverwege de maand al vooruitbetaalt voor de volgende maand).
# Vervangt het vroegere losse "vooruitbetaling_dagen"-giswerk, dat structureel
# vroeg/laat betalende huurders soms als "te veel"/"niet ontvangen" door
# elkaar liet zien in de betaalgeschiedenis.
_EFFECTIEVE_MAAND_GRENSDAG = 17


def _effectieve_maand(datum: date) -> tuple[int, int]:
    if datum.day <= _EFFECTIEVE_MAAND_GRENSDAG:
        return (datum.year, datum.month)
    if datum.month == 12:
        return (datum.year + 1, 1)
    return (datum.year, datum.month + 1)


def _vorige_maand(jaar: int, maand: int) -> tuple[int, int]:
    return (jaar - 1, 12) if maand == 1 else (jaar, maand - 1)


def _zoek_vanaf_voor_maand(vandaag: date) -> date:
    """Startpunt van de bunq-zoekopdracht voor de controle van `vandaag`s
    maand: de 18e van de vorige maand, want vanaf die dag tellen betalingen
    al voor de huidige maand (zie _effectieve_maand)."""
    vorig_jaar, vorige_maand = _vorige_maand(vandaag.year, vandaag.month)
    return date(vorig_jaar, vorige_maand, _EFFECTIEVE_MAAND_GRENSDAG + 1)


def _parse_datum_dmy(tekst: str) -> date | None:
    """Parseert een vrije-tekst datum zoals opgeslagen in kolom 'Contract
    startdatum'. Bedoeld formaat is dd-mm-jjjj, maar wie rechtstreeks in de
    Google Sheet typt houdt zich daar niet altijd aan - vandaar ook
    dd/mm/jjjj, dd.mm.jjjj, het ISO-formaat jjjj-mm-dd (met of zonder
    tijdstempel, zoals Google Sheets een datumcel soms opslaat) en losse
    Nederlandse tekst als "1 juli 2026". Geeft None terug als de tekst geen
    (herkenbare) datum is."""
    tekst = tekst.strip()
    for formaat in (
        "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d",
        "%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(tekst, formaat).date()
        except ValueError:
            continue
    delen = tekst.lower().split()
    if len(delen) == 3:
        dag_tekst, maandnaam, jaar_tekst = delen
        maandnr = _MAAND_NAAM_NAAR_NUMMER.get(maandnaam)
        if maandnr and dag_tekst.isdigit() and jaar_tekst.isdigit():
            try:
                return date(int(jaar_tekst), maandnr, int(dag_tekst))
            except ValueError:
                return None
    return None


def _pro_rata_huur(verwacht_bedrag: Decimal, start: date) -> Decimal:
    """Huur voor de instapmaand naar rato van het aantal dagen dat de
    huurder daadwerkelijk in die maand huurt (vanaf de startdatum, die dag
    meegeteld). Bij een start op de 1e is dit gewoon de volle maandhuur."""
    dagen_in_maand = calendar.monthrange(start.year, start.month)[1]
    resterende_dagen = dagen_in_maand - start.day + 1
    return (verwacht_bedrag * resterende_dagen / dagen_in_maand).quantize(Decimal("0.01"))


def _verwacht_bedrag_voor_maand(tenant: Tenant, maand_sleutel: tuple[int, int]) -> Decimal:
    """Voor de kalendermaand waarin de huurder is ingestapt (kolom 'Contract
    startdatum') is het redelijkerwijs te verwachten bedrag de pro-rata huur
    over de resterende dagen van die maand, plus de waarborgsom (kolom
    'Borg') - huurders betalen die vaak in één keer samen met (een deel van)
    de eerste huur, en dat mag niet als "te veel ontvangen" verschijnen. Voor
    elke andere maand blijft het gewoon de volle maandhuur."""
    start = _parse_datum_dmy(tenant.contract_startdatum) if tenant.contract_startdatum else None
    if not start or (start.year, start.month) != maand_sleutel:
        return tenant.verwacht_bedrag
    return _pro_rata_huur(tenant.verwacht_bedrag, start) + (tenant.borg_bedrag or Decimal("0"))


def run_check(
    config: Config, pand: Pand, dry_run: bool = False
) -> tuple[list[Tenant], list[TenantResult], list[Payment]]:
    vandaag = date.today()
    huidige_maand_sleutel = (vandaag.year, vandaag.month)
    zoek_vanaf = _zoek_vanaf_voor_maand(vandaag)

    logger.info("[%s] Kamers ophalen uit Google Sheet...", pand.slug)
    sheet = SheetClient(config, pand)
    tenants = sheet.get_tenants()
    logger.info("[%s] %d kamers met huurder gevonden", pand.slug, len(tenants))

    # Voor een huurder die deze maand is ingestapt geldt tijdelijk een
    # aangepast verwacht bedrag (pro-rata huur + borg) i.p.v. de volle
    # maandhuur - zie _verwacht_bedrag_voor_maand(). Dit raakt alleen de
    # matching/status van déze controle, niet de "Totale huur"-kolom in de
    # sheet zelf (die wordt door write_results() niet aangepast).
    tenants_voor_match = [
        dataclasses.replace(t, verwacht_bedrag=_verwacht_bedrag_voor_maand(t, huidige_maand_sleutel))
        for t in tenants
    ]

    logger.info("[%s] Betalingen ophalen via bunq sinds %s...", pand.slug, zoek_vanaf)
    bunq = BunqClient(config)
    alle_payments = bunq.get_incoming_payments(pand, since=zoek_vanaf)
    # Betalingen die (per de 17e-grens) eigenlijk voor een andere maand
    # tellen (bv. al vroeg vooruitbetaald voor volgende maand) horen niet bij
    # déze controle - die komen vanzelf mee bij de controle van die maand.
    payments = [p for p in alle_payments if _effectieve_maand(p.datum) == huidige_maand_sleutel]
    logger.info("[%s] %d inkomende betalingen gevonden deze maand", pand.slug, len(payments))

    results, unmatched = match_tenants_to_payments(tenants_voor_match, payments, config.bedrag_tolerantie)

    if not dry_run:
        maand = vandaag.strftime("%Y-%m")
        sheet.write_results(results)
        try:
            sheet.upsert_history(results, maand)
        except Exception:
            # De actuele status (hierboven, en state.save() hieronder) is al
            # opgeslagen - een hapering bij het wegschrijven van de Historie-
            # sheet mag de rest van de controle niet laten mislukken. De
            # kamerpagina vult de lopende maand zo nodig zelf aan vanuit de
            # state-cache (zie webapp/reliability.py:voeg_actuele_maand_toe).
            logger.exception("[%s] Bijwerken van de Historie-sheet voor %s is mislukt.", pand.slug, maand)
        state.save(pand.slug, results, len(unmatched), config.state_dir)
        logger.info("[%s] Sheet en geschiedenis bijgewerkt.", pand.slug)
        _meld_indien_alles_betaald(config, pand, results, maand)

    return tenants, results, unmatched


def _meld_indien_alles_betaald(config: Config, pand: Pand, results: list[TenantResult], maand: str) -> None:
    """Stuurt eenmalig per pand per maand een kennisgeving naar de
    beheerder(s) zodra de huur van alle kamers binnen is - handig omdat de
    dagelijkse automatische controle (zie scripts/dagelijkse_controle.py)
    niemand actief in de gaten houdt."""
    if not results or not all(r.status == Status.BETAALD for r in results):
        return
    if state.email_verzonden_op(pand.slug, _ALLES_BETAALD_KAMER_SLEUTEL, _ALLES_BETAALD_SOORT, maand, config.state_dir):
        return  # deze maand al eerder gemeld

    ontvangers = list(dict.fromkeys(config.email_bcc + pand.extra_bcc))
    if not ontvangers:
        logger.info(
            "[%s] Geen EMAIL_BCC/extra_bcc-adressen ingesteld - 'alles betaald'-melding overgeslagen.", pand.slug
        )
        return

    jaar, maandnr = maand.split("-")
    maandtekst = f"{_MAAND_NAMEN_NL[int(maandnr) - 1]} {jaar}"
    onderwerp = f"Alle huur ontvangen - {pand.naam} - {maandtekst}"
    tekst = (
        f"Beste beheerder,\n\n"
        f"De huur van alle kamers van {pand.naam} is voor {maandtekst} volledig ontvangen.\n\n"
        f"Geen verdere actie nodig.\n\n"
        f"- Steenhub (automatisch bericht)"
    )
    try:
        verstuur_email(config, ", ".join(ontvangers), onderwerp, tekst)
    except MailError:
        logger.exception("[%s] Versturen van 'alles betaald'-melding is mislukt.", pand.slug)
        return
    state.markeer_email_verzonden(pand.slug, _ALLES_BETAALD_KAMER_SLEUTEL, _ALLES_BETAALD_SOORT, maand, config.state_dir)


def _voorgaande_maanden(vandaag: date, aantal: int) -> list[tuple[int, int]]:
    """Geeft `aantal` kalendermaanden vóór (dus exclusief) de maand van
    `vandaag` terug, oudste eerst. De huidige maand wordt bewust overgeslagen -
    die wordt al door run_check() bijgehouden."""
    maanden = []
    jaar, maand = vandaag.year, vandaag.month
    for _ in range(aantal):
        maand -= 1
        if maand == 0:
            maand, jaar = 12, jaar - 1
        maanden.append((jaar, maand))
    maanden.reverse()
    return maanden


def _verdeel_over_maanden(
    verwacht_bedrag: Decimal,
    betalingen: list[Payment],
    maanden: list[tuple[int, int]],
    tolerantie: Decimal,
    verwacht_per_maand: dict[tuple[int, int], Decimal] | None = None,
) -> dict[str, tuple[Decimal, Status, date | None, Decimal]]:
    """Bepaalt per maand het ontvangen bedrag/status op basis van de
    'effectieve maand' van elke betaling (zie _effectieve_maand: 1e t/m 17e
    telt voor die maand, 18e t/m einde van de maand voor de maand erna) - een
    vaste regel in plaats van per-kalendermaand giswerk, zodat een huurder
    die structureel vroeg/laat betaalt niet als "te veel"/"niet ontvangen"
    door elkaar heen wordt weergegeven.

    `verwacht_per_maand` overschrijft `verwacht_bedrag` voor specifieke
    maanden (gebruikt voor de instapmaand: pro-rata huur + borg, zie
    _verwacht_bedrag_voor_maand()) - het teruggegeven bedrag komt terug als
    4e element van de tuple, zodat de Historie-sheet ook voor die maand een
    kloppend "Verwacht bedrag" laat zien in plaats van de volle maandhuur.

    Bewust GEEN cumulatieve verrekening over de hele periode: een
    huurverhoging halverwege de teruggezochte maanden zou dan het
    verwachte/ontvangen bedrag van alle latere maanden laten verschuiven en
    fout weergeven (de sheet houdt geen historische huurbedragen bij). Elke
    maand wordt hier onafhankelijk beoordeeld op basis van precies de
    betalingen met die effectieve maand."""
    per_maand: dict[tuple[int, int], tuple[Decimal, date | None]] = {sleutel: (Decimal("0"), None) for sleutel in maanden}
    for p in betalingen:
        sleutel = _effectieve_maand(p.datum)
        if sleutel not in per_maand:
            continue  # buiten de teruggezochte periode (bv. voor de eerstvolgende maand)
        bedrag, laatste_datum = per_maand[sleutel]
        nieuwe_datum = max(laatste_datum, p.datum) if laatste_datum else p.datum
        per_maand[sleutel] = (bedrag + p.bedrag, nieuwe_datum)

    resultaat: dict[str, tuple[Decimal, Status, date | None, Decimal]] = {}
    for sleutel in maanden:
        ontvangen, laatste_datum = per_maand[sleutel]
        verwacht_deze_maand = (verwacht_per_maand or {}).get(sleutel, verwacht_bedrag)
        maand_key = f"{sleutel[0]}-{sleutel[1]:02d}"
        resultaat[maand_key] = (
            ontvangen, _bepaal_status(ontvangen, verwacht_deze_maand, tolerantie), laatste_datum, verwacht_deze_maand,
        )

    return resultaat


def _maanden_vanaf(start_maand: tuple[int, int], vandaag: date) -> list[tuple[int, int]]:
    """Alle kalendermaanden vanaf (en met) `start_maand` t/m de maand vóór
    `vandaag` (die wordt al door run_check() bijgehouden), oudste eerst.
    Lege lijst als de huurder deze maand (of later) is/gaat instappen."""
    maanden = []
    jaar, maand = start_maand
    while (jaar, maand) < (vandaag.year, vandaag.month):
        maanden.append((jaar, maand))
        maand += 1
        if maand == 13:
            maand, jaar = 1, jaar + 1
    return maanden


def backfill_geschiedenis(
    config: Config, pand: Pand, aantal_maanden: int = 12, vandaag: date | None = None
) -> int:
    """Vult de betaalgeschiedenis (Historie-tabblad) aan op basis van de
    HUIDIGE huurderslijst uit de sheet. Voor een huurder met een bekende
    'Contract startdatum' wordt teruggezocht vanaf díe instapmaand (dus niet
    standaard 'aantal_maanden' terug) - zo verschijnen er geen "niet
    ontvangen"-maanden van vóórdat de huurder er woonde. Voor een huurder
    zonder bekende startdatum blijft de standaard 'aantal_maanden' terug
    gelden. In de instapmaand zelf wordt bovendien rekening gehouden met de
    pro-rata huur (bij een start halverwege de maand) plus een eventuele
    waarborgsom (kolom 'Borg'), zodat die maand niet als "te veel ontvangen"
    verschijnt. Raakt de Huurders-tab (status/ontvangen/laatst gecontroleerd)
    niet aan, alleen de Historie-tab. Geeft het aantal bijgewerkte
    (kamer-onafhankelijke) kalendermaanden terug."""
    vandaag = vandaag or date.today()
    standaard_maanden = _voorgaande_maanden(vandaag, aantal_maanden)

    sheet = SheetClient(config, pand)
    verwijderd = sheet.dedupliceer_geschiedenis()
    if verwijderd:
        logger.info("[%s] %d dubbele historieregel(s) opgeschoond.", pand.slug, verwijderd)
    tenants = sheet.get_tenants()

    maanden_per_kamer: dict[str, list[tuple[int, int]]] = {}
    start_per_kamer: dict[str, date] = {}
    for tenant in tenants:
        start = _parse_datum_dmy(tenant.contract_startdatum) if tenant.contract_startdatum else None
        if start:
            start_per_kamer[tenant.kamer] = start
            maanden_per_kamer[tenant.kamer] = _maanden_vanaf((start.year, start.month), vandaag)
            # Ruimt regels op die een eerdere run (vóórdat de startdatum kon
            # worden gelezen, bv. een toen nog onherkend datumformaat) al
            # verkeerd had teruggerekend tot vóór de werkelijke instapmaand.
            start_maand_sleutel = f"{start.year}-{start.month:02d}"
            opgeschoond = sheet.verwijder_geschiedenis_voor_instapdatum(tenant.kamer, tenant.naam, start_maand_sleutel)
            if opgeschoond:
                logger.info(
                    "[%s] %d historieregel(s) van vóór de instapdatum van %s (kamer %s) opgeschoond.",
                    pand.slug, opgeschoond, tenant.naam, tenant.kamer,
                )
        else:
            maanden_per_kamer[tenant.kamer] = standaard_maanden

    alle_maanden = sorted(set().union(*maanden_per_kamer.values())) if maanden_per_kamer else []
    if not alle_maanden:
        return 0

    oudste_jaar, oudste_maand = alle_maanden[0]
    # Ook een vroege betaling vlak vóór de oudste teruggezochte maand kan al
    # voor die maand tellen (zie _effectieve_maand) - zoek daarom vanaf de
    # 18e van de maand ervoor.
    vorig_jaar, vorige_maand = _vorige_maand(oudste_jaar, oudste_maand)
    zoek_vanaf = date(vorig_jaar, vorige_maand, _EFFECTIEVE_MAAND_GRENSDAG + 1)
    nieuwste_jaar, nieuwste_maand = alle_maanden[-1]
    zoek_tot = date(nieuwste_jaar, nieuwste_maand, calendar.monthrange(nieuwste_jaar, nieuwste_maand)[1])

    logger.info("[%s] Geschiedenis aanvullen sinds %s...", pand.slug, zoek_vanaf)
    bunq = BunqClient(config)
    alle_betalingen = bunq.get_incoming_payments(pand, since=zoek_vanaf)
    # betalingen van de huidige maand (die run_check() al afhandelt) horen niet mee te tellen
    betalingen_in_venster = [p for p in alle_betalingen if p.datum <= zoek_tot]

    resultaten, _unmatched = match_tenants_to_payments(tenants, betalingen_in_venster, config.bedrag_tolerantie)

    per_maand: dict[str, list[TenantResult]] = {f"{j}-{m:02d}": [] for j, m in alle_maanden}
    for resultaat in resultaten:
        tenant = resultaat.tenant
        tenant_maanden = maanden_per_kamer.get(tenant.kamer, standaard_maanden)
        if not tenant_maanden:
            continue  # bv. deze maand pas ingestapt - nog niets om aan te vullen

        overrides: dict[tuple[int, int], Decimal] = {}
        start = start_per_kamer.get(tenant.kamer)
        if start and (start.year, start.month) in tenant_maanden:
            overrides[(start.year, start.month)] = _verwacht_bedrag_voor_maand(tenant, (start.year, start.month))

        verdeling = _verdeel_over_maanden(
            tenant.verwacht_bedrag, resultaat.gematchte_betalingen, tenant_maanden, config.bedrag_tolerantie, overrides,
        )
        for maand_key, (ontvangen, status, betaaldatum, verwacht_deze_maand) in verdeling.items():
            tenant_voor_regel = (
                tenant if verwacht_deze_maand == tenant.verwacht_bedrag
                else dataclasses.replace(tenant, verwacht_bedrag=verwacht_deze_maand)
            )
            gematchte_betalingen = (
                [Payment(
                    bedrag=ontvangen, valuta="EUR", tegenpartij_naam=tenant.naam,
                    tegenpartij_iban=tenant.iban, omschrijving="", datum=betaaldatum,
                )]
                if betaaldatum
                else []
            )
            per_maand.setdefault(maand_key, []).append(
                TenantResult(
                    tenant=tenant_voor_regel, ontvangen_bedrag=ontvangen, status=status,
                    gematchte_betalingen=gematchte_betalingen,
                )
            )

    for maand_key, tenant_resultaten in per_maand.items():
        if tenant_resultaten:
            sheet.upsert_history(tenant_resultaten, maand_key)

    logger.info("[%s] Geschiedenis aangevuld voor %d maand(en).", pand.slug, len(alle_maanden))
    return len(alle_maanden)

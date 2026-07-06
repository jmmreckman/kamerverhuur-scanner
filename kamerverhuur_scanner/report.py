"""Bouwt het e-mailrapport (onderwerp + HTML + platte tekst) op basis van de matchresultaten."""
from __future__ import annotations

from datetime import date
from html import escape

from .models import Payment, Status, TenantResult

_STATUS_KLEUR = {
    Status.BETAALD: "#1a7f37",
    Status.TE_WEINIG: "#b35900",
    Status.TE_VEEL: "#b35900",
    Status.NIET_ONTVANGEN: "#c92a2a",
}


def build_report(results: list[TenantResult], unmatched: list[Payment], peildatum: date) -> tuple[str, str, str]:
    """Geeft (onderwerp, html_body, text_body) terug."""
    problemen = [r for r in results if r.status != Status.BETAALD]
    ok_count = len(results) - len(problemen)

    subject = f"Huurcontrole {peildatum:%d-%m-%Y}: {ok_count}/{len(results)} betaald"
    if problemen:
        subject += f" - {len(problemen)} aandachtspunt(en)"

    html_body = _build_html(results, problemen, unmatched, peildatum)
    text_body = _build_text(results, problemen, unmatched, peildatum)
    return subject, html_body, text_body


def _build_html(results, problemen, unmatched, peildatum) -> str:
    parts = [
        f"<p>Huurcontrole per <strong>{peildatum:%d-%m-%Y}</strong>: "
        f"{len(results) - len(problemen)} van {len(results)} huurders in orde.</p>"
    ]

    if problemen:
        parts.append("<h3>Aandachtspunten</h3>")
        parts.append(_table(problemen))
    else:
        parts.append("<p>Geen aandachtspunten, alle huur is correct binnengekomen.</p>")

    parts.append("<h3>Volledig overzicht</h3>")
    parts.append(_table(results))

    if unmatched:
        parts.append("<h3>Niet-gekoppelde inkomende betalingen</h3>")
        parts.append(
            "<p>Deze inkomende betalingen konden niet aan een huurder worden gekoppeld "
            "(controleer handmatig of vul IBAN/zoekwoord aan in de sheet):</p>"
        )
        rows = "".join(
            f"<tr><td>{escape(p.datum.strftime('%d-%m-%Y'))}</td>"
            f"<td>{escape(p.tegenpartij_naam)}</td>"
            f"<td>{p.bedrag:.2f}</td>"
            f"<td>{escape(p.omschrijving)}</td></tr>"
            for p in unmatched
        )
        parts.append(
            "<table cellpadding='6' cellspacing='0' border='1' style='border-collapse:collapse'>"
            "<tr><th>Datum</th><th>Van</th><th>Bedrag</th><th>Omschrijving</th></tr>" + rows + "</table>"
        )

    return "\n".join(parts)


def _table(results: list[TenantResult]) -> str:
    rows = []
    for r in results:
        kleur = _STATUS_KLEUR[r.status]
        rows.append(
            "<tr>"
            f"<td>{escape(r.tenant.naam)}</td>"
            f"<td>{escape(r.tenant.kamer)}</td>"
            f"<td>{r.tenant.verwacht_bedrag:.2f}</td>"
            f"<td>{r.ontvangen_bedrag:.2f}</td>"
            f"<td style='color:{kleur};font-weight:bold'>{escape(r.status.value)}</td>"
            "</tr>"
        )
    return (
        "<table cellpadding='6' cellspacing='0' border='1' style='border-collapse:collapse'>"
        "<tr><th>Naam</th><th>Kamer</th><th>Verwacht</th><th>Ontvangen</th><th>Status</th></tr>"
        + "".join(rows)
        + "</table>"
    )


def _build_text(results, problemen, unmatched, peildatum) -> str:
    lines = [
        f"Huurcontrole per {peildatum:%d-%m-%Y}: "
        f"{len(results) - len(problemen)} van {len(results)} huurders in orde.",
        "",
    ]

    if problemen:
        lines.append("AANDACHTSPUNTEN:")
        for r in problemen:
            lines.append(
                f"- {r.tenant.naam} (kamer {r.tenant.kamer}): {r.status.value} "
                f"(verwacht {r.tenant.verwacht_bedrag:.2f}, ontvangen {r.ontvangen_bedrag:.2f})"
            )
        lines.append("")

    lines.append("VOLLEDIG OVERZICHT:")
    for r in results:
        lines.append(
            f"- {r.tenant.naam} (kamer {r.tenant.kamer}): {r.status.value} "
            f"(verwacht {r.tenant.verwacht_bedrag:.2f}, ontvangen {r.ontvangen_bedrag:.2f})"
        )

    if unmatched:
        lines.append("")
        lines.append("NIET-GEKOPPELDE INKOMENDE BETALINGEN:")
        for p in unmatched:
            lines.append(f"- {p.datum:%d-%m-%Y} | {p.tegenpartij_naam} | {p.bedrag:.2f} | {p.omschrijving}")

    return "\n".join(lines)

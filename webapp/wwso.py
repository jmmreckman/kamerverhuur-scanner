"""Het WWSO-rapport (Wet waardering onzelfstandige woonruimte / puntentelling)
dat per kamer bij het concept-huurcontract hoort - onderin het huurcontract
wordt ernaar verwezen, dus het moet als extra bijlage mee.

De rapporten staan per pand in de Drive onder ``wwso/<jaartal>/<kamernaam>.pdf``
(relatief t.o.v. de pand-hoofdmap, dezelfde structuur voor elk pand). De
bestandsnaam komt overeen met de kamernaam zoals op de site, bv.
``bg tuinkant.pdf``.

Lukt het bijvoegen niet (map bestaat nog niet, verkeerde bestandsnaam, Drive
onbereikbaar), dan gooien we ``WwsoOntbreekt`` zodat de webapp vóór het mailen
kan waarschuwen - de beheerder kan het dan eerst rechtzetten en daarna alsnog
mailen (of bewust zonder verzenden)."""
from __future__ import annotations

from datetime import date

from kamerverhuur_scanner import drive_browse
from kamerverhuur_scanner.config import Config
from kamerverhuur_scanner.models import Pand


class WwsoOntbreekt(RuntimeError):
    """Het WWSO-rapport voor deze kamer kon niet uit de Drive gehaald worden."""


def wwso_jaar(metadata: dict) -> int:
    """Het jaartal-mapje waarin we zoeken: het jaar van de ingangsdatum van het
    contract, met het huidige jaar als terugval als die datum ontbreekt of
    onleesbaar is."""
    ruw = (metadata.get("ingangsdatum_iso") or "").strip()
    try:
        return date.fromisoformat(ruw).year
    except ValueError:
        return date.today().year


def _kamer_sleutel(naam: str) -> str:
    """Normaliseert een kamernaam/bestandsnaam voor het vergelijken: kleine
    letters en samengevouwen witruimte, zodat 'BG  Tuinkant' en 'bg tuinkant'
    matchen."""
    return " ".join(naam.lower().split())


def haal_wwso_bijlage(
    config: Config, pand: Pand, kamer: str, jaar: int
) -> tuple[str, str, bytes]:
    """Zoekt in ``wwso/<jaar>`` het PDF-bestand waarvan de naam (zonder .pdf)
    overeenkomt met de kamernaam en geeft het terug als bijlage-tuple
    ``(bestandsnaam, mimetype, inhoud)``. Gooit ``WwsoOntbreekt`` met een
    begrijpelijke uitleg als er niets (bruikbaars) gevonden wordt."""
    kamer = (kamer or "").strip()
    if not kamer:
        raise WwsoOntbreekt(
            "Bij dit contract is geen kamernaam vastgelegd, dus het WWSO-rapport "
            "kon niet opgezocht worden."
        )
    if not drive_browse.is_ingesteld(config):
        raise WwsoOntbreekt(
            "De Drive-koppeling is niet ingesteld (RCLONE_REMOTE ontbreekt), dus "
            "het WWSO-rapport kon niet opgehaald worden."
        )

    map_pad = f"wwso/{jaar}"
    try:
        items = drive_browse.list_bestanden(config, pand, map_pad)
    except drive_browse.DriveBrowseError as exc:
        raise WwsoOntbreekt(
            f"De Drive-map '{map_pad}' kon niet gelezen worden: {exc}"
        ) from exc

    gezocht = _kamer_sleutel(kamer)
    pdfs = [i for i in items if not i.is_map and i.naam.lower().endswith(".pdf")]
    for item in pdfs:
        stam = item.naam[: -len(".pdf")]
        if _kamer_sleutel(stam) == gezocht:
            try:
                inhoud = drive_browse.lees_bestand(config, pand, item.pad)
            except drive_browse.DriveBrowseError as exc:
                raise WwsoOntbreekt(
                    f"Het WWSO-rapport '{item.naam}' kon niet gedownload worden: {exc}"
                ) from exc
            return (item.naam, "application/pdf", inhoud)

    if pdfs:
        beschikbaar = ", ".join(sorted(i.naam for i in pdfs))
        raise WwsoOntbreekt(
            f"In '{map_pad}' staat geen WWSO-rapport met de naam '{kamer}.pdf'. "
            f"Aanwezig zijn: {beschikbaar}. Zet het rapport klaar met precies de "
            f"kamernaam als bestandsnaam en probeer opnieuw."
        )
    raise WwsoOntbreekt(
        f"In de Drive-map '{map_pad}' staan (nog) geen WWSO-rapporten. Zet het "
        f"rapport '{kamer}.pdf' klaar en probeer opnieuw."
    )

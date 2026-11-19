"""Nette afwijzingsmail (reservelijst) voor aanmelders die niet zijn
uitgenodigd voor een bezichtiging - Engels, want net als de rest van de
aanmeldingenflow is dit aanmelder-facing."""
from __future__ import annotations

from kamerverhuur_scanner.models import Pand


def standaard_afwijzingsmail(pand: Pand) -> dict[str, str]:
    onderwerp = f"Update on your application - {pand.naam}"
    tekst = (
        "Dear applicant,\n\n"
        f"Thank you for applying for a room at {pand.naam} via our website. We received more "
        "responses than we expected, and after careful consideration we have made a selection - "
        "unfortunately you were not selected this time.\n\n"
        "We have added you to our reserve list: if a spot becomes available, we will get in touch.\n\n"
        "Thank you again for your interest, and we wish you good luck with your search.\n\n"
        "Kind regards,\nSteenhub"
    )
    return {"onderwerp": onderwerp, "tekst": tekst}

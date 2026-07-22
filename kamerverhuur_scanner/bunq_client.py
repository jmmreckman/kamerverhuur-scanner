"""Ophalen van inkomende betalingen via de (officiele, inmiddels niet meer actief
ontwikkelde) bunq Python SDK. Zie scripts/setup_bunq.py voor de eenmalige koppeling.
"""
from __future__ import annotations

from datetime import date, datetime

from bunq.sdk.context.api_context import ApiContext
from bunq.sdk.context.bunq_context import BunqContext
from bunq.sdk.model.generated.endpoint import MonetaryAccountBankApiObject as MonetaryAccountBank
from bunq.sdk.model.generated.endpoint import PaymentApiObject as BunqPayment

from .config import Config
from .models import Pand, Payment
from .utils import parse_bedrag

_PAGINA_GROOTTE = 200


class BunqClientError(RuntimeError):
    pass


class BunqClient:
    def __init__(self, config: Config):
        self._config = config
        self._load_context()

    def _load_context(self) -> None:
        try:
            api_context = ApiContext.restore(self._config.bunq_conf_file)
        except FileNotFoundError as exc:
            raise BunqClientError(
                f"Kon bunq-context bestand '{self._config.bunq_conf_file}' niet vinden. "
                "Draai eerst eenmalig 'python scripts/setup_bunq.py' om de koppeling met "
                "bunq tot stand te brengen (zie README)."
            ) from exc
        api_context.ensure_session_active()
        api_context.save(self._config.bunq_conf_file)
        BunqContext.load_api_context(api_context)

    def get_incoming_payments(self, pand: Pand, since: date) -> list[Payment]:
        """Geeft alle inkomende (positieve) betalingen sinds `since`, alleen op de
        rekening die bij dit pand hoort (voorkomt dat privé-rekeningen of
        rekeningen van andere panden worden meegescand)."""
        return self._get_payments(pand, since, inkomend=True)

    def get_outgoing_payments(self, pand: Pand, since: date) -> list[Payment]:
        """Geeft alle uitgaande betalingen sinds `since` (bedrag als positief
        getal), alleen op de rekening van dit pand - gebruikt door
        kamerverhuur_scanner/winst.py om terugkerende vaste lasten (energie,
        internet, VvE, hypotheek, etc.) te herkennen."""
        return self._get_payments(pand, since, inkomend=False)

    def _get_payments(self, pand: Pand, since: date, inkomend: bool) -> list[Payment]:
        doel_iban = pand.bunq_rekening_iban.replace(" ", "").upper()
        payments: list[Payment] = []
        gevonden_rekening = False

        for account in MonetaryAccountBank.list().value:
            if getattr(account, "status", "ACTIVE") != "ACTIVE":
                continue
            if _account_iban(account) != doel_iban:
                continue
            gevonden_rekening = True
            payments.extend(self._get_payments_for_account(account.id_, since, inkomend))

        if not gevonden_rekening:
            raise BunqClientError(
                f"Geen actieve bunq-rekening gevonden met IBAN '{pand.bunq_rekening_iban}' "
                f"voor pand '{pand.naam}'. Controleer of dit IBAN klopt in properties.json en "
                "of de API key toegang heeft tot deze rekening."
            )
        return payments

    def _get_payments_for_account(self, account_id: int, since: date, inkomend: bool = True) -> list[Payment]:
        """Paginated ophalen: blijft verder terug in de tijd bladeren tot de hele
        periode sinds `since` gehad is, ongeacht hoeveel transacties er op de
        rekening staan. `inkomend=True` geeft alleen positieve (ontvangen)
        bedragen terug (voor de huurcontrole), `inkomend=False` alleen
        uitgaande bedragen (als positief getal, voor de winstberekening)."""
        resultaten: list[Payment] = []
        params = {"count": _PAGINA_GROOTTE}

        while True:
            pagina = BunqPayment.list(monetary_account_id=account_id, params=params).value
            if not pagina:
                break

            oudste_op_pagina_voor_since = False
            for bunq_payment in pagina:
                payment_date = _parse_bunq_datetime(bunq_payment.created).date()
                if payment_date < since:
                    oudste_op_pagina_voor_since = True
                    continue

                bedrag = parse_bedrag(bunq_payment.amount.value)
                if inkomend and bedrag <= 0:
                    continue  # uitgaande betaling, niet relevant voor huurcontrole
                if not inkomend and bedrag >= 0:
                    continue  # inkomende betaling, niet relevant voor de lastenscan

                # counterparty_alias is een MonetaryAccountReference: de naam/IBAN
                # van de tegenpartij staan genest onder .label_monetary_account,
                # niet direct op counterparty_alias zelf.
                label = getattr(bunq_payment.counterparty_alias, "label_monetary_account", None)
                resultaten.append(
                    Payment(
                        bedrag=abs(bedrag),
                        valuta=bunq_payment.amount.currency,
                        tegenpartij_naam=getattr(label, "display_name", "") or "",
                        tegenpartij_iban=(getattr(label, "iban", None) or None),
                        omschrijving=bunq_payment.description or "",
                        datum=payment_date,
                    )
                )

            # bunq sorteert nieuw -> oud, dus zodra we oudere data zien hoeven we niet verder
            if oudste_op_pagina_voor_since or len(pagina) < _PAGINA_GROOTTE:
                break
            params = {"count": _PAGINA_GROOTTE, "older_id": pagina[-1].id_}

        return resultaten


def _account_iban(account) -> str | None:
    for alias in getattr(account, "alias", None) or []:
        if getattr(alias, "type_", None) == "IBAN":
            return (getattr(alias, "value", "") or "").replace(" ", "").upper()
    return None


def _parse_bunq_datetime(raw: str) -> datetime:
    # bunq geeft datums terug als bv. "2026-07-03 10:15:00.000000"
    return datetime.strptime(raw.split(".")[0], "%Y-%m-%d %H:%M:%S")

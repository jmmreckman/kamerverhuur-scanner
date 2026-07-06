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
from .models import Payment
from .utils import parse_bedrag


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

    def get_incoming_payments(self, since: date) -> list[Payment]:
        """Geeft alle inkomende (positieve) betalingen op alle actieve rekeningen sinds `since`."""
        payments: list[Payment] = []
        accounts = MonetaryAccountBank.list().value
        for account in accounts:
            if getattr(account, "status", "ACTIVE") != "ACTIVE":
                continue
            page = BunqPayment.list(monetary_account_id=account.id_, params={"count": 200}).value
            for bunq_payment in page:
                bedrag = parse_bedrag(bunq_payment.amount.value)
                if bedrag <= 0:
                    continue  # uitgaande betaling, niet relevant voor huurcontrole
                payment_date = _parse_bunq_datetime(bunq_payment.created).date()
                if payment_date < since:
                    continue
                counterparty = bunq_payment.counterparty_alias
                payments.append(
                    Payment(
                        bedrag=bedrag,
                        valuta=bunq_payment.amount.currency,
                        tegenpartij_naam=getattr(counterparty, "display_name", "") or "",
                        tegenpartij_iban=(getattr(counterparty, "iban", None) or None),
                        omschrijving=bunq_payment.description or "",
                        datum=payment_date,
                    )
                )
        return payments


def _parse_bunq_datetime(raw: str) -> datetime:
    # bunq geeft datums terug als bv. "2026-07-03 10:15:00.000000"
    return datetime.strptime(raw.split(".")[0], "%Y-%m-%d %H:%M:%S")

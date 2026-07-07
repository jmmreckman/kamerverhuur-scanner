"""Mock-based tests voor de IBAN-filter en paginering in bunq_client.py
(geen echte bunq-verbinding nodig)."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import pytest

from kamerverhuur_scanner.bunq_client import BunqClient, BunqClientError


@dataclass
class FakeConfig:
    bunq_conf_file: str = "fake.conf"


def _pand(iban="NL81BUNQ2163127125"):
    return SimpleNamespace(naam="Mahoniestraat 15", bunq_rekening_iban=iban)


def _account(id_, iban, status="ACTIVE"):
    return SimpleNamespace(id_=id_, status=status, alias=[SimpleNamespace(type_="IBAN", value=iban)])


def _payment(id_, amount, created, counterparty_iban="NL00OTHER0000000000", omschrijving="huur"):
    return SimpleNamespace(
        id_=id_,
        amount=SimpleNamespace(value=amount, currency="EUR"),
        created=created,
        counterparty_alias=SimpleNamespace(display_name="Test Huurder", iban=counterparty_iban),
        description=omschrijving,
    )


@pytest.fixture(autouse=True)
def _geen_echte_bunq_context():
    with mock.patch.object(BunqClient, "_load_context", lambda self: None):
        yield


def test_filtert_op_iban_en_negeert_andere_rekeningen():
    accounts = [
        _account(1, "NL11PRIVE0000000001"),  # priverekening -> moet genegeerd worden
        _account(2, "NL81BUNQ2163127125"),  # de juiste rekening
        _account(3, "NL22ANDERPAND000003"),  # ander pand -> moet genegeerd worden
    ]
    payments_per_account = {
        1: [_payment(101, "500.00", "2026-07-05 10:00:00.000000")],
        2: [_payment(201, "745.00", "2026-07-03 09:00:00.000000")],
        3: [_payment(301, "919.00", "2026-07-02 09:00:00.000000")],
    }

    with mock.patch("kamerverhuur_scanner.bunq_client.MonetaryAccountBank") as MockAccount, mock.patch(
        "kamerverhuur_scanner.bunq_client.BunqPayment"
    ) as MockPayment:
        MockAccount.list.return_value = SimpleNamespace(value=accounts)
        MockPayment.list.side_effect = lambda monetary_account_id, params: SimpleNamespace(
            value=[] if params.get("older_id") else payments_per_account.get(monetary_account_id, [])
        )

        result = BunqClient(FakeConfig()).get_incoming_payments(_pand(), since=date(2026, 7, 1))

    assert len(result) == 1
    assert result[0].bedrag == Decimal("745.00")


def test_paginering_stopt_pas_voorbij_since_datum():
    account = _account(1, "NL81BUNQ2163127125")
    pagina_1 = [
        _payment(103, "100.00", "2026-07-06 10:00:00.000000"),
        _payment(102, "100.00", "2026-07-05 10:00:00.000000"),
    ]
    pagina_2 = [
        _payment(101, "745.00", "2026-07-01 10:00:00.000000"),  # nog net binnen since
        _payment(100, "50.00", "2026-06-29 10:00:00.000000"),  # voor since -> stopteken
    ]
    calls = {"n": 0}

    def fake_list(monetary_account_id, params):
        calls["n"] += 1
        if calls["n"] == 1:
            assert "older_id" not in params
            return SimpleNamespace(value=pagina_1)
        if calls["n"] == 2:
            assert params.get("older_id") == pagina_1[-1].id_
            return SimpleNamespace(value=pagina_2)
        raise AssertionError("had niet nog een pagina moeten ophalen na het zien van oudere data")

    with mock.patch("kamerverhuur_scanner.bunq_client.MonetaryAccountBank") as MockAccount, mock.patch(
        "kamerverhuur_scanner.bunq_client.BunqPayment"
    ) as MockPayment, mock.patch("kamerverhuur_scanner.bunq_client._PAGINA_GROOTTE", 2):
        MockAccount.list.return_value = SimpleNamespace(value=[account])
        MockPayment.list.side_effect = fake_list

        result = BunqClient(FakeConfig()).get_incoming_payments(_pand(), since=date(2026, 7, 1))

    assert sorted(p.bedrag for p in result) == [Decimal("100.00"), Decimal("100.00"), Decimal("745.00")]
    assert calls["n"] == 2


def test_geen_matchende_rekening_geeft_duidelijke_fout():
    with mock.patch("kamerverhuur_scanner.bunq_client.MonetaryAccountBank") as MockAccount:
        MockAccount.list.return_value = SimpleNamespace(value=[_account(1, "NL00WATANDERS00000")])
        with pytest.raises(BunqClientError, match="NL81BUNQ2163127125"):
            BunqClient(FakeConfig()).get_incoming_payments(_pand(), since=date(2026, 7, 1))

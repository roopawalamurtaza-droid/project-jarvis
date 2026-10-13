"""Exact bookkeeping, inventory reservations, manual provenance, and inert adapters."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, localcontext

import pytest

from jarvis import business
from jarvis.business import (
    BusinessLedger,
    MessagingAdapterConfiguration,
    OfficialMessagingAdapter,
    format_minor,
    money_to_minor,
    sample_summary,
)


@pytest.fixture
def ledger(tmp_path):
    return BusinessLedger(tmp_path)


def inventory(ledger, *, quantity=10, currency="INR", cost="10.00", sku="demo"):
    return ledger.add_inventory("Local demo item", sku, quantity, cost, currency)


def totals(ledger, currency="INR"):
    return next(
        entry for entry in ledger.summary()["totals_by_currency"] if entry["currency"] == currency
    )


def test_amounts_are_exact_and_independent_of_decimal_context():
    with localcontext() as context:
        context.prec = 2
        assert money_to_minor("10.01", "INR") == 1001
        assert money_to_minor(Decimal("0.10"), "USD") == 10
        assert money_to_minor(Decimal("1.230000"), "INR") == 123
    assert format_minor(1001, "INR") == "10.01"
    assert format_minor(-1, "USD") == "-0.01"
    assert money_to_minor("100", "JPY") == 100
    assert format_minor(100, "JPY") == "100"
    assert money_to_minor("0.001", "KWD") == 1
    assert format_minor(1, "KWD") == "0.001"


@pytest.mark.parametrize(
    "value,currency",
    [
        (0.1, "INR"),
        (True, "INR"),
        (100, "INR"),
        ("0.001", "INR"),
        ("0.1", "JPY"),
        ("-1", "INR"),
        ("NaN", "INR"),
        (Decimal("NaN"), "INR"),
        (Decimal("Infinity"), "INR"),
        (Decimal("1E100000000"), "INR"),
        (Decimal("1E-100000000"), "INR"),
        ("9999999999999", "INR"),
        ("1,000.00", "INR"),
        ("1e2", "INR"),
        ("1", "XYZ"),
    ],
)
def test_invalid_money_is_rejected_without_rounding(value, currency):
    with pytest.raises(ValueError):
        money_to_minor(value, currency)


@pytest.mark.parametrize("quantity", [0, -1, 1.5, True, "2", 100001])
def test_inventory_requires_bounded_integer_quantity(ledger, quantity):
    with pytest.raises(ValueError):
        inventory(ledger, quantity=quantity)
    assert ledger.inventory() == []


def test_new_ledger_is_empty_and_does_not_seed_or_touch_assistant_memory(ledger, tmp_path):
    assert ledger.path.name == "business.sqlite3"
    assert ledger.summary()["product_count"] == 0
    assert ledger.summary()["totals_by_currency"] == []
    assert not (tmp_path / "jarvis.sqlite3").exists()
    assert not (tmp_path / "settings.json").exists()


def test_order_quantity_cost_and_profit_reservations(ledger):
    product = inventory(ledger)
    order = ledger.create_order(product["id"], 2, "25.00", "3.00")
    assert order["gross_sale_minor"] == 5000
    assert order["purchase_cost_minor"] == 2000
    assert order["potential_profit_minor"] == 2700
    assert order["status"] == "pending"
    assert order["externally_verified"] is False
    assert ledger.inventory()[0]["quantity"] == 10
    assert ledger.inventory()[0]["reserved_quantity"] == 2
    assert ledger.inventory()[0]["available_quantity"] == 8
    assert totals(ledger)["realized_profit_minor"] == 0
    paid = ledger.confirm_payment(order["id"], "manual demo reference")
    assert paid["payment_confirmed_manually"] is True
    assert paid["payment_source"] == "manual_user_confirmation"
    assert paid["externally_verified"] is False
    assert totals(ledger)["recorded_received_minor"] == 5000
    assert totals(ledger)["realized_profit_minor"] == 0
    completed = ledger.fulfill_order(order["id"])
    assert completed["status"] == "recorded_fulfilled"
    assert ledger.inventory()[0]["quantity"] == 8
    assert ledger.inventory()[0]["reserved_quantity"] == 0
    result = totals(ledger)
    assert result["completed_revenue_minor"] == 5000
    assert result["completed_purchase_cost_minor"] == 2000
    assert result["completed_transaction_cost_minor"] == 300
    assert result["realized_profit_minor"] == 2700
    assert result["display"]["realized_profit"] == "27.00"


def test_duplicate_payment_fulfillment_and_refund_are_not_double_counted(ledger):
    product = inventory(ledger)
    order = ledger.create_order(product["id"], 2, "25.00", "3.00")
    ledger.confirm_payment(order["id"], "same reference")
    ledger.confirm_payment(order["id"], "same reference")
    with pytest.raises(ValueError, match="already recorded"):
        ledger.confirm_payment(order["id"], "different reference")
    ledger.fulfill_order(order["id"])
    ledger.fulfill_order(order["id"])
    assert ledger.inventory()[0]["quantity"] == 8
    assert totals(ledger)["recorded_received_minor"] == 5000
    assert totals(ledger)["realized_profit_minor"] == 2700
    assert ledger.summary()["manually_paid_count"] == 1


def test_paid_cancellation_keeps_payment_and_refund_due_until_manual_refund(ledger):
    product = inventory(ledger)
    order = ledger.create_order(product["id"], 4, "25.00", "2.00")
    ledger.confirm_payment(order["id"], "paid outside JARVIS")
    ledger.cancel_order(order["id"])
    ledger.cancel_order(order["id"])
    assert ledger.inventory()[0]["quantity"] == 10
    assert ledger.inventory()[0]["available_quantity"] == 10
    result = totals(ledger)
    assert result["recorded_received_minor"] == 10000
    assert result["recorded_refunded_minor"] == 0
    assert result["refund_due_minor"] == 10000
    assert result["realized_profit_minor"] == 0
    assert result["cancelled_transaction_cost_minor"] == 200
    assert result["profit_after_recorded_cancelled_costs_minor"] == -200
    refund = ledger.record_refund(order["id"], "refunded outside JARVIS")
    assert refund["refund_recorded_manually"]
    assert refund["externally_verified"] is False
    ledger.record_refund(order["id"], "refunded outside JARVIS")
    result = totals(ledger)
    assert result["recorded_received_minor"] == 10000
    assert result["recorded_refunded_minor"] == 10000
    assert result["recorded_net_received_minor"] == 0
    assert result["refund_due_minor"] == 0
    with pytest.raises(ValueError, match="already recorded"):
        ledger.record_refund(order["id"], "different refund")


def test_unpaid_cancelled_order_has_no_payment_or_profit(ledger):
    product = inventory(ledger)
    order = ledger.create_order(product["id"], 2, "25.00", "2.00")
    ledger.cancel_order(order["id"])
    assert totals(ledger)["recorded_received_minor"] == 0
    assert totals(ledger)["refund_due_minor"] == 0
    assert totals(ledger)["realized_profit_minor"] == 0
    with pytest.raises(ValueError, match="cancelled"):
        ledger.confirm_payment(order["id"])
    with pytest.raises(ValueError, match="cancelled, manually paid"):
        ledger.record_refund(order["id"])


def test_fulfillment_requires_manual_payment_and_does_not_deliver_anything(ledger):
    product = inventory(ledger)
    order = ledger.create_order(product["id"], 2, "25.00")
    with pytest.raises(ValueError, match="Record payment"):
        ledger.fulfill_order(order["id"])
    assert ledger.inventory()[0]["quantity"] == 10
    ledger.confirm_payment(order["id"])
    ledger.fulfill_order(order["id"])
    with pytest.raises(ValueError, match="returns are not implemented"):
        ledger.cancel_order(order["id"])
    with pytest.raises(ValueError, match="cancelled, manually paid"):
        ledger.record_refund(order["id"])


def test_reservations_prevent_oversell_and_cancel_releases_stock(ledger):
    product = inventory(ledger, quantity=5)
    first = ledger.create_order(product["id"], 4, "20.00")
    with pytest.raises(ValueError, match="unreserved"):
        ledger.create_order(product["id"], 2, "20.00")
    ledger.cancel_order(first["id"])
    second = ledger.create_order(product["id"], 5, "20.00")
    assert second["quantity"] == 5
    assert ledger.inventory()[0]["available_quantity"] == 0


def test_two_ledger_connections_reserve_atomically(tmp_path):
    first, second = BusinessLedger(tmp_path), BusinessLedger(tmp_path)
    product = inventory(first, quantity=5)

    def reserve(ledger):
        try:
            return ledger.create_order(product["id"], 4, "20.00")
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, [first, second]))
    assert sum(result is not None for result in results) == 1
    assert first.inventory()[0]["reserved_quantity"] == 4
    assert first.summary()["order_count"] == 1


def test_mixed_currencies_never_create_a_combined_money_total(ledger):
    for currency in ("INR", "USD", "JPY", "KWD"):
        product = inventory(ledger, currency=currency, cost="10", sku=currency)
        order = ledger.create_order(product["id"], 2, "20", "1")
        ledger.confirm_payment(order["id"])
        ledger.fulfill_order(order["id"])
    summary = ledger.summary()
    assert "realized_profit_minor" not in summary
    assert {entry["currency"] for entry in summary["totals_by_currency"]} == {
        "INR",
        "USD",
        "JPY",
        "KWD",
    }
    assert totals(ledger, "JPY")["realized_profit_minor"] == 19
    assert totals(ledger, "INR")["realized_profit_minor"] == 1900
    assert totals(ledger, "KWD")["realized_profit_minor"] == 19000


def test_loss_is_reported_as_exact_negative_profit(ledger):
    product = inventory(ledger, cost="10.00")
    order = ledger.create_order(product["id"], 3, "5.00", "1.00")
    ledger.confirm_payment(order["id"])
    ledger.fulfill_order(order["id"])
    assert totals(ledger)["realized_profit_minor"] == -1600
    assert totals(ledger)["display"]["realized_profit"] == "-16.00"


def test_records_survive_restart_and_export_retains_manual_provenance(ledger, tmp_path):
    product = inventory(ledger)
    order = ledger.create_order(product["id"], 2, "25.00", customer_reference="User-entered alias")
    ledger.confirm_payment(order["id"], "user reference")
    ledger.fulfill_order(order["id"])
    reopened = BusinessLedger(tmp_path)
    exported = reopened.export()
    assert len(exported["inventory"]) == len(exported["orders"]) == 1
    assert exported["orders"][0]["customer_reference"] == "User-entered alias"
    assert exported["orders"][0]["payment_source"] == "manual_user_confirmation"
    assert exported["orders"][0]["externally_verified"] is False
    assert totals(reopened)["realized_profit_minor"] == 3000


def test_unknown_ids_and_duplicate_skus_are_rejected(ledger):
    inventory(ledger, sku="abc")
    with pytest.raises(ValueError, match="SKU already exists"):
        inventory(ledger, sku="ABC")
    with pytest.raises(ValueError, match="not found"):
        ledger.create_order("unknown", 1, "25.00")
    with pytest.raises(ValueError, match="not found"):
        ledger.confirm_payment("unknown")


def test_id_whitespace_does_not_create_false_payment_or_fulfillment_claim(ledger):
    product = inventory(ledger)
    order = ledger.create_order(product["id"], 2, "25.00")
    paid = ledger.confirm_payment(" " + order["id"] + " ")
    assert paid["payment_confirmed_manually"]
    result = ledger.fulfill_order(" " + order["id"] + " ")
    assert result["status"] == "recorded_fulfilled"


def test_clear_requires_explicit_boolean_confirmation(ledger):
    product = inventory(ledger)
    ledger.create_order(product["id"], 1, "25.00")
    with pytest.raises(ValueError, match="Explicit confirmation"):
        ledger.clear()
    with pytest.raises(ValueError, match="Explicit confirmation"):
        ledger.clear(confirm="yes")
    assert ledger.summary()["order_count"] == 1
    ledger.clear(confirm=True)
    assert ledger.summary()["order_count"] == 0
    assert ledger.summary()["product_count"] == 0


def test_fictional_sample_is_ephemeral_and_honestly_labelled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    first = sample_summary()
    assert first["is_sample"] is True
    assert first["source"] == "fictional_sample"
    assert first["externally_verified"] is False
    assert first["order_count"] == 2
    assert first["pending_count"] == 1
    assert first["totals_by_currency"][0]["display"]["realized_profit"] == "90.00"
    first["totals_by_currency"][0]["realized_profit_minor"] = 0
    assert sample_summary()["totals_by_currency"][0]["realized_profit_minor"] == 9000
    assert list(tmp_path.iterdir()) == []


def test_daily_summary_honestly_uses_creation_date_and_current_status(ledger, monkeypatch):
    monkeypatch.setattr(business, "_now", lambda: "2026-10-14T01:00:00+00:00")
    product = inventory(ledger)
    order = ledger.create_order(product["id"], 2, "25.00")
    ledger.confirm_payment(order["id"])
    ledger.fulfill_order(order["id"])
    assert ledger.daily_summary("2026-10-14")["order_count"] == 1
    assert ledger.daily_summary("2026-10-13")["order_count"] == 0
    assert "current recorded status" in ledger.daily_summary("2026-10-14")["period_basis"]
    with pytest.raises(ValueError):
        ledger.daily_summary("2026-02-31")


def test_record_limits_and_bounded_output(ledger, monkeypatch):
    monkeypatch.setattr(business, "MAX_PRODUCTS", 1)
    monkeypatch.setattr(business, "MAX_ORDERS", 1)
    product = inventory(ledger)
    with pytest.raises(ValueError, match="Inventory record limit"):
        inventory(ledger, sku="new")
    ledger.create_order(product["id"], 1, "25.00")
    with pytest.raises(ValueError, match="Order record limit"):
        ledger.create_order(product["id"], 1, "25.00")
    assert len(ledger.orders(limit=100000)) == 1
    assert len(ledger.inventory(limit=100000)) == 1


@pytest.mark.parametrize("channel", ["whatsapp_business", "line_messaging"])
def test_official_messaging_foundation_is_inert_even_when_configuration_is_present(channel):
    configuration = MessagingAdapterConfiguration(channel, "123456789", "official_account_token")
    adapter = OfficialMessagingAdapter(configuration)
    status = adapter.status()
    assert status["configuration_fields_present"]
    assert status["operational"] is False
    assert status["sending_implemented"] is False
    assert "token" not in status
    assert "account_id" not in status
    with pytest.raises(NotImplementedError, match="no message has been sent"):
        adapter.send_message("recipient", "content")


@pytest.mark.parametrize(
    "channel,account,credential",
    [
        ("personal_whatsapp", "", ""),
        ("line_messaging", "https://host", ""),
        ("whatsapp_business", "123", "EAA-plaintext-token"),
        ("line_messaging", "123", "x" * 100),
    ],
)
def test_adapter_configuration_rejects_personal_accounts_urls_and_secret_values(
    channel, account, credential
):
    with pytest.raises(ValueError):
        MessagingAdapterConfiguration(channel, account, credential)

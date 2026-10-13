"""An optional local inventory/order ledger, separate from assistant memory.

Amounts are decimal strings at the boundary and integer currency minor units in
SQLite. Nothing here contacts payment providers, delivers inventory, sends a
message, or imports financial records. Payment/refund confirmation and fulfillment
are explicit user-entered bookkeeping, never external verification. Financial
records are not automatically expired or fed to an AI provider.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

# This foundation intentionally supports a defined set rather than assuming all
# ISO currencies have two decimals. Unsupported currencies require an explicit
# exponent addition and tests before use.
CURRENCY_DECIMALS = {
    "INR": 2,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "AUD": 2,
    "CAD": 2,
    "SGD": 2,
    "AED": 2,
    "JPY": 0,
    "KRW": 0,
    "KWD": 3,
    "BHD": 3,
}
MAX_QUANTITY = 100_000
MAX_PRICE_MINOR = 1_000_000_000_000
MAX_PRODUCTS = 2_000
MAX_ORDERS = 20_000


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _currency(value: str) -> str:
    if not isinstance(value, str) or value.strip().upper() not in CURRENCY_DECIMALS:
        raise ValueError("Choose a supported currency: " + ", ".join(CURRENCY_DECIMALS))
    return value.strip().upper()


def _text(value: str, label: str, *, required: bool = True, maximum: int = 160) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    value = value.strip()
    if (required and not value) or len(value) > maximum or re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError(f"{label} must contain up to {maximum} ordinary text characters")
    return value


def _quantity(value: int) -> int:
    if type(value) is not int or not 1 <= value <= MAX_QUANTITY:
        raise ValueError(f"Quantity must be an integer from 1 to {MAX_QUANTITY}")
    return value


def money_to_minor(value: str | Decimal, currency: str) -> int:
    """Parse an exact nonnegative monetary amount; floats/rounding are rejected."""
    currency = _currency(currency)
    if isinstance(value, str):
        value = value.strip()
        if not re.fullmatch(r"\d{1,13}(?:\.\d{1,3})?", value):
            raise ValueError("Enter a nonnegative decimal amount, without commas or exponents")
    elif not isinstance(value, Decimal):
        raise ValueError("Money must be an exact decimal string or Decimal, never a float")
    try:
        amount = Decimal(value)
        if not amount.is_finite():
            raise ValueError("Monetary amount is negative, nonfinite, or above the ledger limit")
        sign, digits_tuple, exponent = amount.as_tuple()
        digits = list(digits_tuple)
        # Work with exact integer digits, independent of global Decimal precision
        # and rounding settings. Strip zeros before considering huge exponents.
        while digits and digits[-1] == 0:
            digits.pop()
            exponent += 1
        if not digits:
            return 0
        places = CURRENCY_DECIMALS[currency]
        if exponent < -places:
            raise ValueError(f"{currency} supports {CURRENCY_DECIMALS[currency]} decimal places")
        if sign or len(digits) + exponent + places > 13:
            raise ValueError("Monetary amount is negative or above the ledger limit")
        minor = int("".join(map(str, digits))) * 10 ** (exponent + places)
        if minor > MAX_PRICE_MINOR:
            raise ValueError("Monetary amount is above the ledger limit")
        return minor
    except InvalidOperation as exc:
        raise ValueError("Invalid exact monetary amount") from exc


def format_minor(value: int, currency: str) -> str:
    currency = _currency(currency)
    if type(value) is not int:
        raise ValueError("Minor currency units must be an integer")
    places = CURRENCY_DECIMALS[currency]
    sign = "-" if value < 0 else ""
    absolute = abs(value)
    if places == 0:
        return sign + str(absolute)
    whole, fraction = divmod(absolute, 10**places)
    return f"{sign}{whole}.{fraction:0{places}d}"


def _inventory_record(row) -> dict:
    record = dict(row)
    record["available_quantity"] = record["quantity"] - record["reserved_quantity"]
    record["unit_purchase_price"] = format_minor(
        record["unit_purchase_price_minor"], record["currency"]
    )
    record["inventory_purchase_cost_minor"] = (
        record["quantity"] * record["unit_purchase_price_minor"]
    )
    return record


def _order_record(row) -> dict:
    record = dict(row)
    record["gross_sale_minor"] = record["quantity"] * record["unit_sale_price_minor"]
    record["purchase_cost_minor"] = record["quantity"] * record["unit_purchase_price_minor"]
    record["potential_profit_minor"] = (
        record["gross_sale_minor"]
        - record["purchase_cost_minor"]
        - record["transaction_cost_minor"]
    )
    record["unit_sale_price"] = format_minor(record["unit_sale_price_minor"], record["currency"])
    record["transaction_cost"] = format_minor(record["transaction_cost_minor"], record["currency"])
    record["payment_confirmed_manually"] = bool(record["payment_confirmed_manually"])
    record["refund_recorded_manually"] = bool(record["refund_recorded_manually"])
    record["externally_verified"] = False
    return record


_FINANCIAL_FIELDS = (
    "inventory_purchase_cost_minor",
    "completed_revenue_minor",
    "completed_purchase_cost_minor",
    "completed_transaction_cost_minor",
    "realized_profit_minor",
    "recorded_received_minor",
    "recorded_refunded_minor",
    "recorded_net_received_minor",
    "refund_due_minor",
    "cancelled_transaction_cost_minor",
    "profit_after_recorded_cancelled_costs_minor",
)


def _summarize(products, orders, *, sample: bool = False) -> dict:
    currencies: dict[str, dict] = {}

    def totals(currency):
        if currency not in currencies:
            currencies[currency] = {"currency": currency} | dict.fromkeys(_FINANCIAL_FIELDS, 0)
        return currencies[currency]

    product_count = inventory_quantity = reserved_quantity = order_count = 0
    pending_count = fulfilled_count = cancelled_count = manually_paid_count = 0
    for product in products:
        product_count += 1
        inventory_quantity += product["quantity"]
        reserved_quantity += product["reserved_quantity"]
        totals(product["currency"])["inventory_purchase_cost_minor"] += (
            product["quantity"] * product["unit_purchase_price_minor"]
        )
    for order in orders:
        order_count += 1
        pending_count += order["status"] == "pending"
        fulfilled_count += order["status"] == "recorded_fulfilled"
        cancelled_count += order["status"] == "cancelled"
        entry = totals(order["currency"])
        if not order["payment_confirmed_manually"]:
            continue
        manually_paid_count += 1
        gross = order["quantity"] * order["unit_sale_price_minor"]
        entry["recorded_received_minor"] += gross
        if order["refund_recorded_manually"]:
            entry["recorded_refunded_minor"] += gross
        if order["status"] == "cancelled":
            entry["cancelled_transaction_cost_minor"] += order["transaction_cost_minor"]
            if not order["refund_recorded_manually"]:
                entry["refund_due_minor"] += gross
        elif order["status"] == "recorded_fulfilled":
            entry["completed_revenue_minor"] += gross
            entry["completed_purchase_cost_minor"] += (
                order["quantity"] * order["unit_purchase_price_minor"]
            )
            entry["completed_transaction_cost_minor"] += order["transaction_cost_minor"]
    for entry in currencies.values():
        entry["realized_profit_minor"] = (
            entry["completed_revenue_minor"]
            - entry["completed_purchase_cost_minor"]
            - entry["completed_transaction_cost_minor"]
        )
        entry["recorded_net_received_minor"] = (
            entry["recorded_received_minor"] - entry["recorded_refunded_minor"]
        )
        entry["profit_after_recorded_cancelled_costs_minor"] = (
            entry["realized_profit_minor"] - entry["cancelled_transaction_cost_minor"]
        )
        entry["display"] = {
            field.removesuffix("_minor"): format_minor(entry[field], entry["currency"])
            for field in _FINANCIAL_FIELDS
        }
    return {
        "source": "fictional_sample" if sample else "local_user_entered",
        "is_sample": sample,
        "payment_verification": "manual_user_confirmation_only",
        "externally_verified": False,
        "product_count": product_count,
        "inventory_quantity": inventory_quantity,
        "reserved_quantity": reserved_quantity,
        "order_count": order_count,
        "pending_count": pending_count,
        "recorded_fulfilled_count": fulfilled_count,
        "cancelled_count": cancelled_count,
        "manually_paid_count": manually_paid_count,
        "totals_by_currency": [currencies[key] for key in sorted(currencies)],
        "profit_scope": "Recorded fulfilled, manually paid orders; cancelled costs shown separately.",
    }


class BusinessLedger:
    """Short-lived SQLite connections; writes serialize across threads/processes.

    Instantiate only when the user chooses their local ledger. Inventory/orders
    are user-entered records, not a connection to the actual game or bank. Pending
    orders reserve stock; recorded fulfillment decrements ledger stock once.
    Financial sums use Python integers, avoiding SQLite SUM overflow/float coercion.
    """

    def __init__(self, data_dir: Path | str):
        root = Path(data_dir)
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "business.sqlite3"
        self._lock = threading.RLock()
        with sqlite3.connect(self.path, timeout=5) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError("Business ledger was created by a newer JARVIS version")
            db.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS products (
                    id TEXT PRIMARY KEY, sku TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK(quantity>=0),
                    unit_purchase_price_minor INTEGER NOT NULL CHECK(unit_purchase_price_minor>=0),
                    currency TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(id),
                    quantity INTEGER NOT NULL CHECK(quantity>0),
                    unit_purchase_price_minor INTEGER NOT NULL CHECK(unit_purchase_price_minor>=0),
                    unit_sale_price_minor INTEGER NOT NULL CHECK(unit_sale_price_minor>=0),
                    transaction_cost_minor INTEGER NOT NULL CHECK(transaction_cost_minor>=0),
                    currency TEXT NOT NULL, status TEXT NOT NULL,
                    customer_reference TEXT NOT NULL DEFAULT '',
                    payment_confirmed_manually INTEGER NOT NULL DEFAULT 0,
                    payment_reference TEXT NOT NULL DEFAULT '', payment_recorded_at TEXT,
                    payment_source TEXT NOT NULL DEFAULT 'unverified',
                    refund_recorded_manually INTEGER NOT NULL DEFAULT 0,
                    refund_reference TEXT NOT NULL DEFAULT '', refund_recorded_at TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    CHECK(status IN ('pending','recorded_fulfilled','cancelled')));
                CREATE INDEX IF NOT EXISTS business_orders_product ON orders(product_id,status);
                PRAGMA user_version=1;
            """)

    @contextmanager
    def _connect(self, *, write: bool = False):
        with self._lock:
            db = sqlite3.connect(self.path, timeout=5)
            db.row_factory = sqlite3.Row
            try:
                db.execute("PRAGMA foreign_keys=ON")
                db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                with db:
                    yield db
            finally:
                db.close()

    @staticmethod
    def _get_order(db, order_id: str):
        order_id = _text(order_id, "Order ID", maximum=36)
        row = db.execute(
            "SELECT orders.*,products.name AS product_name,products.sku "
            "FROM orders JOIN products ON products.id=orders.product_id WHERE orders.id=?",
            (order_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Order not found")
        return row

    def add_inventory(
        self,
        name: str,
        sku: str,
        quantity: int,
        unit_purchase_price: str | Decimal,
        currency: str = "INR",
    ) -> dict:
        name, sku = _text(name, "Product name"), _text(sku, "SKU", maximum=80).upper()
        quantity, currency = _quantity(quantity), _currency(currency)
        price = money_to_minor(unit_purchase_price, currency)
        identity = str(uuid.uuid4())
        with self._connect(write=True) as db:
            if db.execute("SELECT COUNT(*) FROM products").fetchone()[0] >= MAX_PRODUCTS:
                raise ValueError("Inventory record limit reached; export or clear explicitly")
            if db.execute("SELECT 1 FROM products WHERE sku=?", (sku,)).fetchone():
                raise ValueError("This SKU already exists")
            db.execute(
                "INSERT INTO products VALUES(?,?,?,?,?,?,?)",
                (identity, sku, name, quantity, price, currency, _now()),
            )
            row = db.execute(
                "SELECT *,0 AS reserved_quantity FROM products WHERE id=?", (identity,)
            ).fetchone()
            return _inventory_record(row)

    def create_order(
        self,
        product_id: str,
        quantity: int,
        unit_sale_price: str | Decimal,
        transaction_cost: str | Decimal = "0.00",
        *,
        customer_reference: str = "",
    ) -> dict:
        product_id = _text(product_id, "Product ID", maximum=36)
        quantity = _quantity(quantity)
        customer_reference = _text(customer_reference, "Customer reference", required=False)
        identity, timestamp = str(uuid.uuid4()), _now()
        with self._connect(write=True) as db:
            if db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] >= MAX_ORDERS:
                raise ValueError("Order record limit reached; export or clear explicitly")
            product = db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
            if product is None:
                raise ValueError("Inventory product not found")
            reserved = db.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM orders WHERE product_id=? AND status='pending'",
                (product_id,),
            ).fetchone()[0]
            if quantity > product["quantity"] - reserved:
                raise ValueError("Not enough unreserved inventory for this order")
            sale = money_to_minor(unit_sale_price, product["currency"])
            costs = money_to_minor(transaction_cost, product["currency"])
            db.execute(
                "INSERT INTO orders(id,product_id,quantity,unit_purchase_price_minor,"
                "unit_sale_price_minor,transaction_cost_minor,currency,status,customer_reference,"
                "created_at,updated_at) VALUES(?,?,?,?,?,?,?,'pending',?,?,?)",
                (
                    identity,
                    product_id,
                    quantity,
                    product["unit_purchase_price_minor"],
                    sale,
                    costs,
                    product["currency"],
                    customer_reference,
                    timestamp,
                    timestamp,
                ),
            )
            return _order_record(self._get_order(db, identity))

    def confirm_payment(self, order_id: str, reference: str = "") -> dict:
        """Record the user's confirmation; this does not verify a bank/payment API."""
        reference = _text(reference, "Payment reference", required=False)
        with self._connect(write=True) as db:
            order = self._get_order(db, order_id)
            order_id = order["id"]
            if order["status"] == "cancelled":
                raise ValueError("Cannot confirm payment for a cancelled order")
            if order["payment_confirmed_manually"]:
                if reference != order["payment_reference"]:
                    raise ValueError(
                        "Payment is already recorded; its reference cannot be replaced"
                    )
                return _order_record(order)
            timestamp = _now()
            db.execute(
                "UPDATE orders SET payment_confirmed_manually=1,payment_reference=?,"
                "payment_recorded_at=?,payment_source='manual_user_confirmation',updated_at=? "
                "WHERE id=?",
                (reference, timestamp, timestamp, order_id),
            )
            return _order_record(self._get_order(db, order_id))

    def fulfill_order(self, order_id: str) -> dict:
        """Record external fulfillment manually; no inventory is delivered by JARVIS."""
        with self._connect(write=True) as db:
            order = self._get_order(db, order_id)
            order_id = order["id"]
            if order["status"] == "recorded_fulfilled":
                return _order_record(order)
            if order["status"] != "pending" or not order["payment_confirmed_manually"]:
                raise ValueError(
                    "Record payment manually before recording pending-order fulfillment"
                )
            updated = db.execute(
                "UPDATE products SET quantity=quantity-? WHERE id=? AND quantity>=?",
                (order["quantity"], order["product_id"], order["quantity"]),
            )
            if updated.rowcount != 1:
                raise ValueError("Recorded inventory cannot cover this fulfillment")
            db.execute(
                "UPDATE orders SET status='recorded_fulfilled',updated_at=? WHERE id=?",
                (_now(), order_id),
            )
            return _order_record(self._get_order(db, order_id))

    def cancel_order(self, order_id: str) -> dict:
        """Release a pending reservation; paid cancellations retain a refund due."""
        with self._connect(write=True) as db:
            order = self._get_order(db, order_id)
            order_id = order["id"]
            if order["status"] == "recorded_fulfilled":
                raise ValueError(
                    "Recorded fulfillment cannot be cancelled; returns are not implemented"
                )
            if order["status"] != "cancelled":
                db.execute(
                    "UPDATE orders SET status='cancelled',updated_at=? WHERE id=?",
                    (_now(), order_id),
                )
            return _order_record(self._get_order(db, order_id))

    def record_refund(self, order_id: str, reference: str = "") -> dict:
        """Record a completed full external refund manually; never transfer money."""
        reference = _text(reference, "Refund reference", required=False)
        with self._connect(write=True) as db:
            order = self._get_order(db, order_id)
            order_id = order["id"]
            if order["status"] != "cancelled" or not order["payment_confirmed_manually"]:
                raise ValueError("Only a cancelled, manually paid order can record a refund")
            if order["refund_recorded_manually"]:
                if reference != order["refund_reference"]:
                    raise ValueError("Refund is already recorded; its reference cannot be replaced")
                return _order_record(order)
            timestamp = _now()
            db.execute(
                "UPDATE orders SET refund_recorded_manually=1,refund_reference=?,"
                "refund_recorded_at=?,updated_at=? WHERE id=?",
                (reference, timestamp, timestamp, order_id),
            )
            return _order_record(self._get_order(db, order_id))

    @staticmethod
    def _product_rows(db, *, limit: int = MAX_PRODUCTS, offset: int = 0):
        return db.execute(
            "SELECT products.*,COALESCE(reserved.quantity,0) AS reserved_quantity FROM products "
            "LEFT JOIN (SELECT product_id,SUM(quantity) AS quantity FROM orders WHERE "
            "status='pending' GROUP BY product_id) reserved ON products.id=reserved.product_id "
            "ORDER BY products.created_at,products.id LIMIT ? OFFSET ?",
            (limit, offset),
        )

    @staticmethod
    def _order_rows(db, *, limit: int = MAX_ORDERS, offset: int = 0):
        return db.execute(
            "SELECT orders.*,products.name AS product_name,products.sku FROM orders "
            "JOIN products ON products.id=orders.product_id ORDER BY orders.created_at,orders.id "
            "LIMIT ? OFFSET ?",
            (limit, offset),
        )

    def inventory(self, limit: int = 200, offset: int = 0) -> list[dict]:
        with self._connect() as db:
            return [
                _inventory_record(row)
                for row in self._product_rows(
                    db,
                    limit=min(max(int(limit), 1), 500),
                    offset=min(max(int(offset), 0), MAX_PRODUCTS),
                )
            ]

    def orders(self, limit: int = 200, offset: int = 0) -> list[dict]:
        with self._connect() as db:
            return [
                _order_record(row)
                for row in self._order_rows(
                    db,
                    limit=min(max(int(limit), 1), 500),
                    offset=min(max(int(offset), 0), MAX_ORDERS),
                )
            ]

    def summary(self) -> dict:
        with self._connect() as db:
            return _summarize(self._product_rows(db), self._order_rows(db))

    def daily_summary(self, day: str) -> dict:
        """Current statuses of orders created on a UTC day; not bank reconciliation."""
        if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError("Choose a UTC order-creation date in YYYY-MM-DD format")
        date.fromisoformat(day)
        with self._connect() as db:
            result = _summarize(
                self._product_rows(db),
                (row for row in self._order_rows(db) if row["created_at"].startswith(day + "T")),
            )
        return result | {
            "day": day,
            "period_basis": "Orders created on this UTC day, using their current recorded status.",
            "inventory_basis": "Current ledger stock, independent of the selected order date.",
        }

    def export(self) -> dict:
        """Complete explicit export; not part of normal prompts/history retention."""
        with self._connect() as db:
            return {
                "schema_version": 1,
                "source": "local_user_entered",
                "externally_verified": False,
                "inventory": [_inventory_record(row) for row in self._product_rows(db)],
                "orders": [_order_record(row) for row in self._order_rows(db)],
            }

    def clear(self, *, confirm: bool = False) -> None:
        if confirm is not True:
            raise ValueError(
                "Explicit confirmation is required to delete the local business ledger"
            )
        with self._connect(write=True) as db:
            db.execute("DELETE FROM orders")
            db.execute("DELETE FROM products")


def sample_summary() -> dict:
    """Fictional, ephemeral example; no database, customer data, or network access."""
    products = [
        {
            "quantity": 8,
            "reserved_quantity": 1,
            "unit_purchase_price_minor": 10_000,
            "currency": "INR",
        }
    ]
    orders = [
        {
            "quantity": 2,
            "unit_sale_price_minor": 15_000,
            "unit_purchase_price_minor": 10_000,
            "transaction_cost_minor": 1_000,
            "currency": "INR",
            "status": "recorded_fulfilled",
            "payment_confirmed_manually": True,
            "refund_recorded_manually": False,
        },
        {
            "quantity": 1,
            "unit_sale_price_minor": 15_000,
            "unit_purchase_price_minor": 10_000,
            "transaction_cost_minor": 0,
            "currency": "INR",
            "status": "pending",
            "payment_confirmed_manually": False,
            "refund_recorded_manually": False,
        },
    ]
    return _summarize(products, orders, sample=True)


@dataclass(frozen=True, slots=True)
class MessagingAdapterConfiguration:
    """Nonsecret placeholders for official accounts and DPAPI credential references."""

    channel: Literal["whatsapp_business", "line_messaging"]
    account_id: str = ""
    credential_name: str = ""

    def __post_init__(self):
        if self.channel not in {"whatsapp_business", "line_messaging"}:
            raise ValueError("Only official WhatsApp Business and LINE Messaging are supported")
        if self.account_id and not re.fullmatch(r"[0-9]{1,32}", self.account_id):
            raise ValueError("Official account identifier must be a bounded numeric ID")
        if self.credential_name and not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.credential_name):
            raise ValueError("Use a secure credential reference name, never a token")


class OfficialMessagingAdapter:
    """A deliberately inactive adapter contract; no personal-account automation.

    Future implementation requires official account setup, credential handling,
    permission checks, request preview, recipient authorization and verified API
    responses. Configuration alone never enables sending.
    """

    def __init__(self, configuration: MessagingAdapterConfiguration):
        self.configuration = configuration

    def status(self) -> dict:
        channel = self.configuration.channel
        return {
            "channel": channel,
            "configuration_fields_present": bool(
                self.configuration.account_id and self.configuration.credential_name
            ),
            "operational": False,
            "sending_implemented": False,
            "reason": "Official API adapter is a foundation only; live messaging is not implemented.",
            "documentation_url": (
                "https://developers.facebook.com/docs/whatsapp/cloud-api/overview"
                if channel == "whatsapp_business"
                else "https://developers.line.biz/en/docs/messaging-api/overview/"
            ),
        }

    def send_message(self, *args, **kwargs):
        raise NotImplementedError("Live messaging is not implemented; no message has been sent")

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The takings of each channel side by side (`D-273`).

Every sales report here can be filtered to one order type, and none puts them
next to each other — so «how much of the month came through the apps, and at
what average bill» meant running a report five times and adding up by hand. In
Saudi Arabia the delivery apps can be half the trade, and they are paid for in
commission: this is the page that says whether they earn it.

**The same money as `Daily Sales`**, grouped by order type instead of by day —
its own functions, not a copy, so the two cannot disagree on a total. **A refund
comes off the channel of the bill it reverses.**

Refs: FR-11.2, D-244, D-273
"""

import frappe
from frappe import _
from frappe.utils import flt

from restaurant_pos.restaurant_pos.report.daily_sales.daily_sales import add_sale, finish, money_of
from restaurant_pos.utils import reporting


def execute(filters=None):
	filters = frappe._dict(filters or {})
	filters.pop("order_type", None)
	from_date, to_date = reporting.window(filters)

	orders = reporting.settled_orders(filters, from_date, to_date, ["sales_invoice", "order_type"])
	invoices = money_of([row.sales_invoice for row in orders])

	channels: dict[str, dict] = {}
	for order in orders:
		money = invoices.get(order.sales_invoice)
		if money:
			add_sale(channels.setdefault(order.order_type, _channel(order.order_type)), money)

	for order_type, total in _refunds_by_channel(filters, from_date, to_date).items():
		channels.setdefault(order_type, _channel(order_type))["returns"] += total

	rows = sorted(channels.values(), key=lambda row: -row["total"])
	for row in rows:
		finish(row)
	takings = sum(row["net"] for row in rows)
	for row in rows:
		row["share"] = flt(row["net"] / takings * 100, 2) if takings else 0.0

	return _columns(), ([*rows, _total(rows)] if rows else rows)


def _channel(order_type: str | None) -> dict:
	title = (
		frappe.db.get_value("Restaurant Order Type", order_type, ["title_ar", "title"], as_dict=True) or {}
	)
	return {
		"order_type": order_type,
		"channel": title.get("title_ar") or title.get("title") or order_type,
		"bills": 0,
		"sales": 0.0,
		"tax": 0.0,
		"total": 0.0,
		"returns": 0.0,
	}


def _refunds_by_channel(filters, from_date: str, to_date: str) -> dict[str, float]:
	credits = reporting.credit_notes(filters, from_date, to_date)
	if not credits:
		return {}

	notes = frappe.get_all(
		"Sales Invoice", filters={"name": ("in", credits)}, fields=["return_against", "grand_total"]
	)
	channel_of = dict(
		frappe.get_all(
			"Restaurant Order",
			filters={"sales_invoice": ("in", [note.return_against for note in notes])},
			fields=["sales_invoice", "order_type"],
			as_list=True,
		)
	)
	refunds: dict[str, float] = {}
	for note in notes:
		order_type = channel_of.get(note.return_against)
		refunds[order_type] = refunds.get(order_type, 0.0) + abs(flt(note.grand_total))
	return refunds


def _total(rows: list[dict]) -> dict:
	total = {"order_type": None, "channel": _("Period Total")}
	for field in ("bills", "sales", "tax", "total", "returns"):
		total[field] = flt(sum(row[field] for row in rows), 2)
	finish(total)
	total["share"] = 100.0 if rows else 0.0
	return total


def _columns() -> list[dict]:
	return [
		{"fieldname": "channel", "label": _("Channel"), "fieldtype": "Data", "width": 170},
		{"fieldname": "bills", "label": _("Bills"), "fieldtype": "Int", "width": 80},
		{"fieldname": "sales", "label": _("Sales before VAT"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "tax", "label": _("VAT"), "fieldtype": "Currency", "width": 100},
		{"fieldname": "total", "label": _("Total"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "returns", "label": _("Returns"), "fieldtype": "Currency", "width": 110},
		{"fieldname": "net", "label": _("Net"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "share", "label": _("Share %"), "fieldtype": "Percent", "width": 90},
		{"fieldname": "average", "label": _("Average Bill"), "fieldtype": "Currency", "width": 110},
	]

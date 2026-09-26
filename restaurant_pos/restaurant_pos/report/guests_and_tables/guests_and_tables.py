# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Guests at each table, how long they stayed, and what they spent a head (`D-274`).

**The numbers a dining room is run on**, and none of the sales reports can say
them: a table that turns four times at 60 a head earns more than one that turns
twice at 90, and only guests and minutes tell the two apart.

**Bills with a table only** — a takeaway has no seat to turn. **Guests are the
count the cashier entered** (`cover_count`); a bill with none is counted as a
turn and left out of the per-head figure rather than guessed at one guest.
**Minutes are from opening the bill to settling it**, which is when the table is
taken and when it is free.

Refs: FR-11.2, D-274
"""

import frappe
from frappe import _
from frappe.utils import flt, time_diff_in_seconds

from restaurant_pos.utils import reporting


def execute(filters=None):
	filters = frappe._dict(filters or {})
	filters.pop("order_type", None)
	from_date, to_date = reporting.window(filters)

	tables: dict[str, dict] = {}
	for order in reporting.settled_orders(
		filters, from_date, to_date, ["table", "cover_count", "total_amount", "opened_at", "closed_at"]
	):
		if not order.table:
			continue
		row = tables.setdefault(
			order.table,
			{
				"table": order.table,
				"turns": 0,
				"guests": 0,
				"counted_sales": 0.0,
				"sales": 0.0,
				"minutes": 0.0,
			},
		)
		row["turns"] += 1
		row["sales"] += flt(order.total_amount)
		if order.cover_count:
			row["guests"] += int(order.cover_count)
			row["counted_sales"] += flt(order.total_amount)
		if order.opened_at and order.closed_at:
			row["minutes"] += max(time_diff_in_seconds(order.closed_at, order.opened_at), 0) / 60

	rows = sorted(tables.values(), key=lambda row: -row["sales"])
	for row in rows:
		_finish(row)
	return _columns(), ([*rows, _total(rows)] if rows else rows)


def _finish(row: dict) -> None:
	row["per_guest"] = flt(row["counted_sales"] / row["guests"], 2) if row["guests"] else 0.0
	row["average_minutes"] = int(row["minutes"] / row["turns"]) if row["turns"] else 0
	row["sales"] = flt(row["sales"], 2)


def _total(rows: list[dict]) -> dict:
	total = {"table": _("Total")}
	for field in ("turns", "guests", "counted_sales", "sales", "minutes"):
		total[field] = sum(row[field] for row in rows)
	_finish(total)
	return total


def _columns() -> list[dict]:
	return [
		{
			"fieldname": "table",
			"label": _("Table"),
			"fieldtype": "Link",
			"options": "Restaurant Table",
			"width": 120,
		},
		{"fieldname": "turns", "label": _("Turns"), "fieldtype": "Int", "width": 80},
		{"fieldname": "guests", "label": _("Guests"), "fieldtype": "Int", "width": 80},
		{"fieldname": "sales", "label": _("Sales"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "per_guest", "label": _("Per Guest"), "fieldtype": "Currency", "width": 110},
		{"fieldname": "average_minutes", "label": _("Minutes a Turn"), "fieldtype": "Int", "width": 120},
	]

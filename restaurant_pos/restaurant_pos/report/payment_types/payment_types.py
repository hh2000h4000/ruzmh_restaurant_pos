# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""How the money came in over a period — cash against card against the apps.

The drawer's report splits its own takings by method, but only for one drawer on
one day. An owner asks the other question: over this month, how much of the trade
was cash — because that is what decides how often somebody walks to the bank, and
what share of the takings a delivery platform is holding.

**Read from the invoice's payment rows**, which is where a payment is recorded
(`D-022`); the order carries none of its own. Submitted invoices only (`D-062`):
a cancelled one reverses the ledger but leaves its payment rows behind.

**Credit is listed and kept apart** (`D-029`). Money owed by a platform was never
in the drawer, so netting it into the takings would say a restaurant holds cash
it has not been paid.

Refs: FR-8.3, FR-11.2, D-022, D-029, D-062, D-247
"""

import frappe
from frappe import _
from frappe.utils import flt

from restaurant_pos.utils import reporting
from restaurant_pos.utils.bulk import get_all_in
from restaurant_pos.utils.payment import is_credit_method
from restaurant_pos.utils.sale_doc import SALE


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date, to_date = reporting.window(filters)

	orders = reporting.settled_orders(filters, from_date, to_date, ["sales_invoice"])
	sold = _submitted([row.sales_invoice for row in orders])
	refunds = reporting.credit_notes(filters, from_date, to_date)

	rows = _tally(sold + refunds)
	takings = sum(row["net"] for row in rows)
	for row in rows:
		row["share"] = flt(row["net"] / takings * 100, 2) if takings else 0.0

	return _columns(), ([*rows, _total(rows)] if rows else rows)


def _submitted(invoices: list[str]) -> list[str]:
	if not invoices:
		return []

	return get_all_in(SALE, filters={"name": ("in", invoices), "docstatus": 1}, pluck="name")


def _tally(invoices: list[str]) -> list[dict]:
	"""Taken and given back per method — apart, because the net hides a busy day."""
	if not invoices:
		return []

	tally: dict[str, dict] = {}
	for row in get_all_in(
		"Sales Invoice Payment",
		filters={"parent": ("in", invoices), "parenttype": SALE},
		fields=["mode_of_payment", "amount"],
	):
		line = tally.setdefault(
			row.mode_of_payment,
			{
				"method": row.mode_of_payment,
				"kind": "credit" if is_credit_method(row.mode_of_payment) else "till",
				"taken": 0.0,
				"refunded": 0.0,
			},
		)
		# A credit note carries negative payment rows, which is how a refund comes
		# back out of the method it was paid from.
		line["taken" if flt(row.amount) >= 0 else "refunded"] += abs(flt(row.amount))

	for line in tally.values():
		line["taken"] = flt(line["taken"], 2)
		line["refunded"] = flt(line["refunded"], 2)
		line["net"] = flt(line["taken"] - line["refunded"], 2)

	return sorted(tally.values(), key=lambda line: (line["kind"], -line["net"]))


def _total(rows: list[dict]) -> dict:
	total = {"method": _("Period Total"), "kind": "", "share": 100.0}
	for field in ("taken", "refunded", "net"):
		total[field] = flt(sum(row[field] for row in rows), 2)

	return total


def _columns() -> list[dict]:
	return [
		{
			"fieldname": "method",
			"label": _("Mode of Payment"),
			"fieldtype": "Link",
			"options": "Mode of Payment",
			"width": 220,
		},
		{"fieldname": "kind", "label": _("Kind"), "fieldtype": "Data", "width": 110},
		{"fieldname": "taken", "label": _("Taken"), "fieldtype": "Currency", "width": 160},
		{"fieldname": "refunded", "label": _("Refunded"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "net", "label": _("Net"), "fieldtype": "Currency", "width": 160},
		{"fieldname": "share", "label": _("Share of Sales %"), "fieldtype": "Float", "width": 140},
	]

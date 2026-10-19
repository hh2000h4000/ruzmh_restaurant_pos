# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""What every sales report over a period asks for, asked once.

Three reports walk the same path — which bills were settled in this window, in
this branch, of this order type, and which refunds were paid out against them —
and they must walk it identically or the item report and the day report will
disagree about the same fortnight. So the walk lives here (`CLAUDE.md` §5.5).

**The dating is `D-217`'s**, the same rule the drawer and the day already use: a
sale counts in the period its bill was settled, whatever day opened it, and a
refund counts in the period it was paid out, against a sale of any age.

Refs: FR-11.2, D-217, D-243
"""

import frappe
from frappe import _
from frappe.utils import getdate

from restaurant_pos.utils.bulk import get_all_in
from restaurant_pos.utils.sale_doc import SALE

#: A bill that took money. Cancelled ones sold nothing.
SETTLED = "closed"


def window(filters) -> tuple[str, str]:
	"""The reported period as two datetimes, so a whole last day is included."""
	if not filters.from_date or not filters.to_date:
		frappe.throw(_("Choose the days to report on."))

	from_date, to_date = getdate(filters.from_date), getdate(filters.to_date)
	if from_date > to_date:
		frappe.throw(_("From Date cannot be after To Date."))

	return f"{from_date} 00:00:00", f"{to_date} 23:59:59"


def scope(filters) -> dict:
	"""The branch, the till and the order type, as filters on `Restaurant Order`.

	**The till is the device the bill was rung up on** (`D-279`) — three tills
	in one branch are three answers to «who sold this?», and every bill already
	carried its `pos_profile`. Here, so every report that walks settled bills
	offers it at once rather than fourteen of them learning it one by one.
	"""
	chosen = {}
	if filters.branch:
		chosen["branch"] = filters.branch
	if filters.pos_profile:
		chosen["pos_profile"] = filters.pos_profile
	if filters.order_type:
		chosen["order_type"] = filters.order_type
	return chosen


def settled_orders(filters, from_date: str, to_date: str, fields: list[str]) -> list[frappe._dict]:
	"""Bills settled inside the window, in scope, with the fields asked for."""
	return frappe.get_all(
		"Restaurant Order",
		filters={
			**scope(filters),
			"status": SETTLED,
			"closed_at": ("between", [from_date, to_date]),
			"sales_invoice": ("is", "set"),
		},
		fields=fields,
	)


def credit_notes(filters, from_date: str, to_date: str) -> list[str]:
	"""Refunds paid out inside the window, against a sale of any age (`D-217`).

	Scoped through the bill they reverse, because a credit note carries no branch
	of its own — the same walk `utils/returns` makes to find a refund's order.
	"""
	credits = frappe.get_all(
		SALE,
		filters={
			"is_return": 1,
			"docstatus": 1,
			"posting_date": ("between", [getdate(from_date), getdate(to_date)]),
			"return_against": ("is", "set"),
		},
		fields=["name", "return_against"],
	)
	if not credits:
		return []

	originals = list({row.return_against for row in credits})
	in_scope = set(
		get_all_in(
			"Restaurant Order",
			filters={**scope(filters), "sales_invoice": ("in", originals)},
			pluck="sales_invoice",
		)
	)

	return [row.name for row in credits if row.return_against in in_scope]

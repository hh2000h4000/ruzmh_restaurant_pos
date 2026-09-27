# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Every discount, void, cancellation and refund in a period — and who allowed it.

Toast calls this the sales exceptions report and says what it is for: seeing the
total and the count per staff member, and **naming the person who gave it and the
one who approved it**. That is the loss-prevention question a restaurant asks
once a week, and until now the only place to ask it was the audit log one row at
a time.

**Read from the trail, not from a second tally.** `POS Audit Log` already records
every one of these with its actor, its approver and its reason, and it cannot be
edited or deleted (`D-205`). A report that counted them again from the orders
would eventually disagree with the record that is actually evidence.

**The amount lives under a different key per action**, because each act means a
different figure — a void is worth the line, a cancellation the whole bill, a
discount what came off. They are read by name rather than guessed at, and an
action carrying no figure shows none instead of a zero that reads as free.

Refs: FR-11.2, FR-12.5, D-205, D-247
"""

import json

import frappe
from frappe import _
from frappe.utils import flt

from restaurant_pos.utils import reporting

#: What counts as an exception, and where each one keeps its amount.
#:
#: `promotion_applied` is deliberately absent: an offer the restaurant published
#: is not an exception, it is the menu. A discount typed by hand is.
AMOUNT_KEYS = {
	"void_item": "amount",
	"void_order": "total_amount",
	"cancel_order": "total_amount",
	"discount_applied": "discount_amount",
	"return_created": "refund_amount",
	"price_change": None,
	"cash_out": "amount",
}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date, to_date = reporting.window(filters)

	rows = _events(filters, from_date, to_date)
	takings = _takings(filters, from_date, to_date)

	if filters.group_by_staff:
		rows = _by_staff(rows)

	total = sum(flt(row.get("amount")) for row in rows)

	# **A share only where it means something.** Measured per person it is the
	# figure Toast prints and the one a manager acts on; against a single act it
	# would read "this one void was 4% of the month", which is not a thought
	# anybody has.
	if filters.group_by_staff:
		for row in rows:
			row["share"] = flt(flt(row.get("amount")) / takings * 100, 2) if takings else 0.0

	return _columns(by_staff=bool(filters.group_by_staff)), rows, _message(total, takings)


# --------------------------------------------------------------------------- #
# The trail
# --------------------------------------------------------------------------- #


def _events(filters, from_date: str, to_date: str) -> list[dict]:
	wanted = [filters.action_type] if filters.action_type else list(AMOUNT_KEYS)

	scope = {"action_type": ("in", wanted), "timestamp": ("between", [from_date, to_date])}
	if filters.branch:
		scope["branch"] = filters.branch
	if filters.pos_profile:
		scope["pos_profile"] = filters.pos_profile
	if filters.cashier:
		scope["cashier"] = filters.cashier

	rows = frappe.get_all(
		"POS Audit Log",
		filters=scope,
		fields=[
			"name",
			"timestamp",
			"action_type",
			"cashier",
			"approved_by",
			"restaurant_order",
			"reason",
			"details",
		],
		order_by="timestamp desc",
	)

	people = _names([row.cashier for row in rows] + [row.approved_by for row in rows])
	for row in rows:
		row["amount"] = _amount_of(row)
		row["by"] = people.get(row.cashier, row.cashier)
		row["approver"] = people.get(row.approved_by, row.approved_by)

	return rows


def _amount_of(row) -> float | None:
	"""What this act cost, read by the key its own action uses."""
	key = AMOUNT_KEYS.get(row.action_type)
	if not key or not row.details:
		return None

	try:
		# **The size, not the sign.** A credit note's total is negative because
		# that is what a credit note is, and every other act here keeps a positive
		# figure. Mixed signs in one column would net a refund against a void and
		# make the total say less came off than did.
		return abs(flt(json.loads(row.details).get(key)))
	except (ValueError, TypeError, AttributeError):
		# A detail blob from an older release, or one written by hand. Saying
		# nothing is honest; a zero would read as "this cost the restaurant
		# nothing", which is the opposite of what the report is for.
		return None


def _names(users: list[str | None]) -> dict[str, str]:
	wanted = [user for user in set(users) if user]
	if not wanted:
		return {}

	return dict(
		frappe.get_all("User", filters={"name": ("in", wanted)}, fields=["name", "full_name"], as_list=True)
	)


def _takings(filters, from_date: str, to_date: str) -> float:
	"""The period's settled bills, so a figure can be read against the trade.

	Toast prints a void percentage for exactly this reason: ten cancellations in
	a thousand covers is a different restaurant from ten in forty.
	"""
	orders = reporting.settled_orders(filters, from_date, to_date, ["total_amount"])
	return sum(flt(row.total_amount) for row in orders)


# --------------------------------------------------------------------------- #
# Grouping
# --------------------------------------------------------------------------- #


def _by_staff(events: list[dict]) -> list[dict]:
	"""One row per person — how often, and for how much."""
	tally: dict[str, dict] = {}

	for event in events:
		row = tally.setdefault(
			event["cashier"] or "",
			{"cashier": event["cashier"], "by": event["by"], "count": 0, "amount": 0.0},
		)
		row["count"] += 1
		row["amount"] += flt(event.get("amount"))

	for row in tally.values():
		row["amount"] = flt(row["amount"], 2)

	return sorted(tally.values(), key=lambda row: row["amount"], reverse=True)


def _message(total: float, takings: float) -> str | None:
	"""Both figures, not one ratio.

	A cancelled bill is money that never became takings and a discount is money
	given away on a bill that did, so dividing their sum by the takings makes a
	percentage that can pass 100 and reads as a fault rather than as the two
	different things it adds together. The manager gets the pair and the
	per-person share below, which is the comparison that holds.
	"""
	if not (total or takings):
		return None

	return _("{0} came off in exceptions, against takings of {1}.").format(flt(total, 2), flt(takings, 2))


# --------------------------------------------------------------------------- #
# Columns
# --------------------------------------------------------------------------- #


def _columns(*, by_staff: bool) -> list[dict]:
	if by_staff:
		return [
			{
				"fieldname": "cashier",
				"label": _("Cashier"),
				"fieldtype": "Link",
				"options": "User",
				"width": 230,
			},
			{"fieldname": "count", "label": _("How Many"), "fieldtype": "Int", "width": 110},
			{"fieldname": "amount", "label": _("Amount"), "fieldtype": "Currency", "width": 150},
			{"fieldname": "share", "label": _("Share of Sales %"), "fieldtype": "Float", "width": 140},
		]

	return [
		{"fieldname": "timestamp", "label": _("Timestamp"), "fieldtype": "Datetime", "width": 160},
		{"fieldname": "action_type", "label": _("Action Type"), "fieldtype": "Data", "width": 140},
		{"fieldname": "cashier", "label": _("Cashier"), "fieldtype": "Link", "options": "User", "width": 200},
		{
			"fieldname": "approved_by",
			"label": _("Approved By"),
			"fieldtype": "Link",
			"options": "User",
			"width": 200,
		},
		{
			"fieldname": "restaurant_order",
			"label": _("Restaurant Order"),
			"fieldtype": "Link",
			"options": "Restaurant Order",
			"width": 170,
		},
		{"fieldname": "reason", "label": _("Reason"), "fieldtype": "Data", "width": 240},
		{"fieldname": "amount", "label": _("Amount"), "fieldtype": "Currency", "width": 140},
	]

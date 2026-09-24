# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""What each coupon — and each campaign — actually brought in (`D-248`).

The user's reason for wanting coupons was an influencer: *anyone who comes
through this person uses this code*. That only means something if the campaign
can be measured afterwards, so this is the measuring: how many bills carried a
code, what they came to, and what the offer behind them gave away.

**Grouped by campaign by default**, because that is the unit a marketing
decision is made about — one influencer may hold two hundred single-use codes,
and two hundred rows answer nothing. The per-code view is a tick away for the
case where a code is suspected of being shared.

**Dated like all the money here** (`D-217`): a bill counts in the period it was
settled.

Refs: FR-11.2, D-217, D-248
"""

import frappe
from frappe import _
from frappe.utils import flt

from restaurant_pos.utils import reporting


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date, to_date = reporting.window(filters)

	orders = reporting.settled_orders(
		filters, from_date, to_date, ["coupon", "total_amount", "promotion_amount"]
	)
	used = [row for row in orders if row.coupon]
	if filters.campaign or filters.coupon:
		used = _narrowed(used, filters)

	rows = _tally(used, by_campaign=not filters.group_by_coupon)
	takings = sum(row["sales"] for row in rows)
	for row in rows:
		row["share"] = flt(row["sales"] / takings * 100, 2) if takings else 0.0

	return _columns(by_campaign=not filters.group_by_coupon), rows


def _narrowed(orders: list, filters) -> list:
	"""Only the codes the manager asked about."""
	wanted = frappe.get_all(
		"POS Coupon",
		filters={
			key: value for key, value in (("campaign", filters.campaign), ("name", filters.coupon)) if value
		},
		pluck="name",
	)
	return [row for row in orders if row.coupon in wanted]


def _tally(orders: list, *, by_campaign: bool) -> list[dict]:
	if not orders:
		return []

	codes = {
		row.name: row
		for row in frappe.get_all(
			"POS Coupon",
			filters={"name": ("in", list({row.coupon for row in orders}))},
			fields=["name", "coupon_code", "campaign", "promotion"],
		)
	}

	tally: dict[str, dict] = {}
	for order in orders:
		code = codes.get(order.coupon)
		if not code:
			continue

		key = (code.campaign or _("No campaign")) if by_campaign else code.name
		row = tally.setdefault(
			key,
			{"campaign": code.campaign, "promotion": code.promotion, "bills": 0, "sales": 0.0, "given": 0.0}
			| ({} if by_campaign else {"coupon": code.name, "coupon_code": code.coupon_code}),
		)
		row["bills"] += 1
		row["sales"] += flt(order.total_amount)
		row["given"] += flt(order.promotion_amount)

	for row in tally.values():
		row["sales"] = flt(row["sales"], 2)
		row["given"] = flt(row["given"], 2)
		row["average"] = flt(row["sales"] / row["bills"], 2) if row["bills"] else 0.0

	return sorted(tally.values(), key=lambda row: row["sales"], reverse=True)


def _columns(*, by_campaign: bool) -> list[dict]:
	head = (
		[{"fieldname": "campaign", "label": _("Campaign"), "fieldtype": "Data", "width": 220}]
		if by_campaign
		else [
			{
				"fieldname": "coupon",
				"label": _("Coupon"),
				"fieldtype": "Link",
				"options": "POS Coupon",
				"width": 160,
			},
			{"fieldname": "campaign", "label": _("Campaign"), "fieldtype": "Data", "width": 180},
		]
	)

	return [
		*head,
		{
			"fieldname": "promotion",
			"label": _("Promotion"),
			"fieldtype": "Link",
			"options": "Restaurant Promotion",
			"width": 160,
		},
		{"fieldname": "bills", "label": _("Bills"), "fieldtype": "Int", "width": 90},
		{"fieldname": "sales", "label": _("Sales"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "given", "label": _("Given Away"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "average", "label": _("Average Bill"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "share", "label": _("Share of Sales %"), "fieldtype": "Float", "width": 140},
	]

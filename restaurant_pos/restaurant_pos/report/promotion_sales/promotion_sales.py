# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""What each offer gave away, on how many bills (`D-274`).

`Coupon Sales` measures the offers a code unlocks, and `Sales Exceptions` leaves
offers out on purpose — an offer is the menu, not an exception (`D-247`). So an
automatic «20% on drinks, three to six» ran for a month with nobody able to say
what it cost or what it brought.

**Read from the bill's own record**: the offer it was filed under and the money
that came off (`D-182`). A bill two offers touched keeps one name and the sum,
by that decision, and this report does not re-run the engine over months of
bills whose offers may since have changed — so on such a bill the whole
discount sits with the recorded offer. The bill does not say that a second offer
touched it, so neither can this; the guide says so where the report is read.

Refs: FR-11.2, BR-034, D-182, D-274
"""

import frappe
from frappe import _
from frappe.utils import flt

from restaurant_pos.utils import reporting


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date, to_date = reporting.window(filters)

	offers: dict[str, dict] = {}
	for order in reporting.settled_orders(
		filters, from_date, to_date, ["promotion", "promotion_amount", "total_amount"]
	):
		if not order.promotion:
			continue
		row = offers.setdefault(
			order.promotion, {"promotion": order.promotion, "bills": 0, "given": 0.0, "sales": 0.0}
		)
		row["bills"] += 1
		row["given"] += flt(order.promotion_amount)
		row["sales"] += flt(order.total_amount)

	titles = (
		{
			row.name: row.title_ar or row.title
			for row in frappe.get_all(
				"Restaurant Promotion",
				filters={"name": ("in", list(offers))},
				fields=["name", "title", "title_ar"],
			)
		}
		if offers
		else {}
	)

	rows = sorted(offers.values(), key=lambda row: -row["given"])
	for row in rows:
		row["title"] = titles.get(row["promotion"], row["promotion"])
		row["given"] = flt(row["given"], 2)
		row["sales"] = flt(row["sales"], 2)
		row["average_given"] = flt(row["given"] / row["bills"], 2)
		row["share"] = flt(row["given"] / (row["sales"] + row["given"]) * 100, 2) if row["sales"] else 0.0
	return _columns(), rows


def _columns() -> list[dict]:
	return [
		{
			"fieldname": "promotion",
			"label": _("Offer"),
			"fieldtype": "Link",
			"options": "Restaurant Promotion",
			"width": 120,
		},
		{"fieldname": "title", "label": _("Title"), "fieldtype": "Data", "width": 200},
		{"fieldname": "bills", "label": _("Bills"), "fieldtype": "Int", "width": 80},
		{"fieldname": "given", "label": _("Given Away"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "sales", "label": _("Sales of Those Bills"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "average_given", "label": _("Given a Bill"), "fieldtype": "Currency", "width": 110},
		{"fieldname": "share", "label": _("Discount %"), "fieldtype": "Percent", "width": 100},
	]

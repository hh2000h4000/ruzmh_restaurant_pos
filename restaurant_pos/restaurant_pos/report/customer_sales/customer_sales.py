# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Who spends most, how often they come, and when they last did (`D-274`).

The regulars a restaurant would miss if they stopped coming, and the ones who
already have — a best customer whose last visit was two months ago is a phone
call, not a figure.

**The walk-in is not a customer here.** Every till has a default customer
(`D-231`) that a bill falls back to when nobody was named; listing it would put
most of the takings on one anonymous line at the top of the page.

Refs: FR-6.3, FR-11.2, D-231, D-274
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from restaurant_pos.utils import reporting


def execute(filters=None):
	filters = frappe._dict(filters or {})
	filters.pop("order_type", None)
	from_date, to_date = reporting.window(filters)

	walk_ins = set(frappe.get_all("POS Profile", filters={"customer": ("is", "set")}, pluck="customer"))

	people: dict[str, dict] = {}
	for order in reporting.settled_orders(
		filters, from_date, to_date, ["customer", "total_amount", "closed_at"]
	):
		if not order.customer or order.customer in walk_ins:
			continue
		row = people.setdefault(
			order.customer,
			{
				"customer": order.customer,
				"bills": 0,
				"total": 0.0,
				"first": order.closed_at,
				"last": order.closed_at,
			},
		)
		row["bills"] += 1
		row["total"] += flt(order.total_amount)
		row["first"] = min(row["first"], order.closed_at)
		row["last"] = max(row["last"], order.closed_at)

	names = (
		dict(
			frappe.get_all(
				"Customer",
				filters={"name": ("in", list(people))},
				fields=["name", "customer_name"],
				as_list=True,
			)
		)
		if people
		else {}
	)

	rows = sorted(people.values(), key=lambda row: -row["total"])
	for row in rows:
		row["customer_name"] = names.get(row["customer"], row["customer"])
		row["total"] = flt(row["total"], 2)
		row["average"] = flt(row["total"] / row["bills"], 2)
		row["first"] = getdate(row["first"])
		row["last"] = getdate(row["last"])
	return _columns(), rows


def _columns() -> list[dict]:
	return [
		{
			"fieldname": "customer",
			"label": _("Customer"),
			"fieldtype": "Link",
			"options": "Customer",
			"width": 150,
		},
		{"fieldname": "customer_name", "label": _("Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "bills", "label": _("Visits"), "fieldtype": "Int", "width": 80},
		{"fieldname": "total", "label": _("Total Spent"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "average", "label": _("Average Bill"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "first", "label": _("First Visit"), "fieldtype": "Date", "width": 110},
		{"fieldname": "last", "label": _("Last Visit"), "fieldtype": "Date", "width": 110},
	]

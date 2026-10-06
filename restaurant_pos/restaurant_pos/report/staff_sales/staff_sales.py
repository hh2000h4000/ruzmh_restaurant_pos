# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""What each person took over a period — the employee sales report every list names.

The drawer's own report already names who took what (`D-218`), but only inside
one drawer on one day. The question an owner actually asks is the other one:
over this month, who sold how much, and what came back on them.

**Attributed to whoever took the money** (`D-188`), not to whoever opened the
bill: a ticket started at eleven and settled at three by the next cashier is
theirs, and that is how the drawer counts it too. The two reports therefore
cannot disagree about the same fortnight.

**The average is takings over bills**, computed per row and again for the whole
period — never a mean of means (`D-244`).

Refs: FR-8.3, FR-11.2, D-188, D-218, D-247
"""

import frappe
from frappe import _
from frappe.utils import flt

from restaurant_pos.utils import reporting
from restaurant_pos.utils.sale_doc import SALE


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date, to_date = reporting.window(filters)

	orders = reporting.settled_orders(
		filters, from_date, to_date, ["cashier", "total_amount", "sales_invoice"]
	)
	refunds = _refunds(reporting.credit_notes(filters, from_date, to_date))

	people: dict[str, dict] = {}
	for order in orders:
		row = _person(people, order.cashier)
		row["bills"] += 1
		row["sales"] += flt(order.total_amount)

	for owner, amount in refunds.items():
		_person(people, owner)["returns"] += amount

	rows = sorted(people.values(), key=lambda row: row["sales"], reverse=True)
	_name_them(rows)

	takings = sum(row["sales"] for row in rows)
	for row in rows:
		_finish(row)
		row["share"] = flt(row["sales"] / takings * 100, 2) if takings else 0.0

	return _columns(), ([*rows, _total(rows)] if rows else rows)


def _person(people: dict, user: str | None) -> dict:
	return people.setdefault(user or "", {"cashier": user, "bills": 0, "sales": 0.0, "returns": 0.0})


def _refunds(credits: list[str]) -> dict[str, float]:
	"""What each person paid back, by whoever made the credit note."""
	if not credits:
		return {}

	tally: dict[str, float] = {}
	for row in frappe.get_all(SALE, filters={"name": ("in", credits)}, fields=["owner", "grand_total"]):
		tally[row.owner] = tally.get(row.owner, 0.0) + abs(flt(row.grand_total))

	return tally


def _name_them(rows: list[dict]) -> None:
	wanted = [row["cashier"] for row in rows if row["cashier"]]
	names = (
		dict(
			frappe.get_all(
				"User", filters={"name": ("in", wanted)}, fields=["name", "full_name"], as_list=True
			)
		)
		if wanted
		else {}
	)
	for row in rows:
		row["staff_name"] = names.get(row["cashier"], row["cashier"])


def _finish(row: dict) -> None:
	row["sales"] = flt(row["sales"], 2)
	row["returns"] = flt(row["returns"], 2)
	row["net"] = flt(row["sales"] - row["returns"], 2)
	row["average"] = flt(row["sales"] / row["bills"], 2) if row["bills"] else 0.0


def _total(rows: list[dict]) -> dict:
	"""Its own, because Frappe's total row would add up the averages (`D-244`)."""
	total = {"cashier": None, "staff_name": _("Period Total"), "share": 100.0}
	for field in ("bills", "sales", "returns"):
		total[field] = flt(sum(row[field] for row in rows), 2)

	_finish(total)
	return total


def _columns() -> list[dict]:
	return [
		{
			"fieldname": "cashier",
			"label": _("Cashier", context="RPOS report"),
			"fieldtype": "Link",
			"options": "User",
			"width": 200,
		},
		{"fieldname": "staff_name", "label": _("Name"), "fieldtype": "Data", "width": 200},
		{"fieldname": "bills", "label": _("Bills"), "fieldtype": "Int", "width": 90},
		{"fieldname": "sales", "label": _("Sales"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "returns", "label": _("Refunded"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "net", "label": _("Net"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "average", "label": _("Average Bill"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "share", "label": _("Share of Sales %"), "fieldtype": "Float", "width": 140},
	]

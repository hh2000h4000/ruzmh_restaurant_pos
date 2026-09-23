# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""A row per day — the report an owner reads to compare one week with the last.

Everything else the app reports is either **one day** (the drawer's X and Z) or
**no days at all** (`Item Sales` sums a period into dishes). Neither answers
"was Thursday better than last Thursday", which is the question a restaurant
runs on, so this is a line per day with the takings and the count.

**The average bill is takings over bills, not a mean of means.** Two days of
1000/10 and 500/20 average 50 a bill across the fortnight, not 37.50 — and the
total row has to say the first, so it is computed there rather than summed.

**The dating is `D-217`'s**, through `utils/reporting`: the same walk the item
report makes, so the two cannot disagree about the same fortnight.

Refs: FR-11.2, D-217, D-244
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from restaurant_pos.utils import reporting

#: Weekdays as Python numbers them, in the order a Saudi week is read.
ARABIC_WEEKDAY = {
	6: "الأحد",
	0: "الإثنين",
	1: "الثلاثاء",
	2: "الأربعاء",
	3: "الخميس",
	4: "الجمعة",
	5: "السبت",
}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date, to_date = reporting.window(filters)

	orders = reporting.settled_orders(filters, from_date, to_date, ["sales_invoice", "closed_at"])
	invoices = _money_of([row.sales_invoice for row in orders])
	refunds = _money_of(reporting.credit_notes(filters, from_date, to_date))

	days: dict[str, dict] = {}
	for order in orders:
		money = invoices.get(order.sales_invoice)
		if money:
			_add_sale(days.setdefault(str(getdate(order.closed_at)), _day(order.closed_at)), money)

	for credit in refunds.values():
		day = days.setdefault(str(getdate(credit.posting_date)), _day(credit.posting_date))
		day["returns"] += abs(flt(credit.grand_total))

	rows = sorted(days.values(), key=lambda row: row["day"])
	for row in rows:
		_finish(row)

	return _columns(), ([*rows, _total(rows)] if rows else rows)


def _day(on) -> dict:
	date = getdate(on)
	return {
		"day": str(date),
		"weekday": ARABIC_WEEKDAY[date.weekday()],
		"bills": 0,
		"sales": 0.0,
		"tax": 0.0,
		"total": 0.0,
		"returns": 0.0,
	}


def _add_sale(day: dict, money) -> None:
	day["bills"] += 1
	day["sales"] += flt(money.net_total)
	day["tax"] += flt(money.total_taxes_and_charges)
	day["total"] += flt(money.grand_total)


def _money_of(invoices: list[str]) -> dict[str, frappe._dict]:
	if not invoices:
		return {}

	rows = frappe.get_all(
		"Sales Invoice",
		filters={"name": ("in", invoices), "docstatus": 1},
		fields=["name", "posting_date", "net_total", "total_taxes_and_charges", "grand_total"],
	)
	return {row.name: row for row in rows}


def _finish(row: dict) -> None:
	row["net"] = flt(row["total"] - row["returns"], 2)
	row["average"] = flt(row["total"] / row["bills"], 2) if row["bills"] else 0.0
	for field in ("sales", "tax", "total", "returns"):
		row[field] = flt(row[field], 2)


def _total(rows: list[dict]) -> dict:
	"""The report's own total row, because Frappe's would add up the averages.

	Two days of 1000 over 10 bills and 500 over 20 average 50 a bill across the
	fortnight, not the 87.50 that summing 100 and 25 gives. So `add_total_row` is
	off and the last line is computed the way the question is asked.
	"""
	total = {"day": None, "weekday": _("Period Total")}
	for field in ("bills", "sales", "tax", "total", "returns"):
		total[field] = flt(sum(row[field] for row in rows), 2)

	_finish(total)
	return total


def _columns() -> list[dict]:
	return [
		{"fieldname": "day", "label": _("Day"), "fieldtype": "Date", "width": 110},
		{"fieldname": "weekday", "label": _("Weekday"), "fieldtype": "Data", "width": 100},
		{"fieldname": "bills", "label": _("Bills"), "fieldtype": "Int", "width": 90},
		{"fieldname": "sales", "label": _("Sales (excl. VAT)"), "fieldtype": "Currency", "width": 150},
		{"fieldname": "tax", "label": _("VAT"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "total", "label": _("Total Taken"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "returns", "label": _("Refunded"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "net", "label": _("Net"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "average", "label": _("Average Bill"), "fieldtype": "Currency", "width": 130},
	]

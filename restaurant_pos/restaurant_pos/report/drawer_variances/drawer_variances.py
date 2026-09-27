# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Every drawer that did not count out as expected, and who closed it (`D-273`).

**The first report an owner opens when money feels short.** The Z report says it
for one drawer on one day; this says it for a month, across every cashier, so a
shortage that keeps landing on the same person reads as a pattern rather than as
thirty separate bad evenings.

**Read from ERPNext's own closing entries** (`D-047`), the same rows the Z report
prints, so the two cannot disagree. The difference is counted less expected: **a
negative figure is money missing**, and the reason the cashier had to give for it
(`BR-043`) sits beside it.

**By cashier** folds the same rows into one line per person: how many drawers,
how many came up short, the shortages and overages apart — a net of zero can hide
a big short and a big over — and the net.

Refs: FR-8.3, BR-043, D-047, D-219, D-273
"""

import frappe
from frappe import _
from frappe.utils import flt

from restaurant_pos.utils import reporting
from restaurant_pos.utils.order import branch_of_profile


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date, to_date = reporting.window(filters)

	rows = closings(filters, from_date, to_date)
	if filters.only_differences:
		rows = [row for row in rows if abs(row["difference"]) >= 0.01]

	if filters.by_cashier:
		return _cashier_columns(), _by_cashier(rows)
	return _columns(), ([*rows, _total(rows)] if rows else rows)


def closings(filters, from_date: str, to_date: str) -> list[dict]:
	"""One line per submitted closing in the period, summed over its methods."""
	conditions = {"docstatus": 1, "period_end_date": ("between", [from_date, to_date])}
	if filters.cashier:
		conditions["user"] = filters.cashier

	entries = frappe.get_all(
		"POS Closing Entry",
		filters=conditions,
		fields=["name", "user", "pos_profile", "period_end_date", "rpos_variance_reason"],
		order_by="period_end_date asc",
	)
	if not entries:
		return []

	details: dict[str, list] = {}
	for row in frappe.get_all(
		"POS Closing Entry Detail",
		filters={"parenttype": "POS Closing Entry", "parent": ("in", [entry.name for entry in entries])},
		fields=["parent", "expected_amount", "closing_amount", "difference"],
	):
		details.setdefault(row.parent, []).append(row)

	names = {}
	rows = []
	for entry in entries:
		if filters.pos_profile and entry.pos_profile != filters.pos_profile:
			continue
		branch = branch_of_profile(entry.pos_profile)
		if filters.branch and branch != filters.branch:
			continue
		lines = details.get(entry.name, [])
		if entry.user not in names:
			names[entry.user] = frappe.db.get_value("User", entry.user, "full_name") or entry.user
		rows.append(
			{
				"closed_at": entry.period_end_date,
				"closing": entry.name,
				"branch": branch,
				"pos_profile": entry.pos_profile,
				"cashier": entry.user,
				"cashier_name": names[entry.user],
				"expected": flt(sum(flt(line.expected_amount) for line in lines), 2),
				"counted": flt(sum(flt(line.closing_amount) for line in lines), 2),
				"difference": flt(sum(flt(line.difference) for line in lines), 2),
				"reason": entry.rpos_variance_reason,
			}
		)
	return rows


def _total(rows: list[dict]) -> dict:
	return {
		"cashier_name": _("Total", context="RPOS report"),
		"expected": flt(sum(row["expected"] for row in rows), 2),
		"counted": flt(sum(row["counted"] for row in rows), 2),
		"difference": flt(sum(row["difference"] for row in rows), 2),
	}


def _by_cashier(rows: list[dict]) -> list[dict]:
	people: dict[str, dict] = {}
	for row in rows:
		line = people.setdefault(
			row["cashier"],
			{
				"cashier": row["cashier"],
				"cashier_name": row["cashier_name"],
				"drawers": 0,
				"short_drawers": 0,
				"short": 0.0,
				"over": 0.0,
			},
		)
		line["drawers"] += 1
		if row["difference"] < 0:
			line["short_drawers"] += 1
			line["short"] += row["difference"]
		else:
			line["over"] += row["difference"]

	lines = sorted(people.values(), key=lambda line: line["short"])
	for line in lines:
		line["short"] = flt(line["short"], 2)
		line["over"] = flt(line["over"], 2)
		line["net"] = flt(line["short"] + line["over"], 2)
	return lines


def _columns() -> list[dict]:
	return [
		{"fieldname": "closed_at", "label": _("Closed At"), "fieldtype": "Datetime", "width": 150},
		{
			"fieldname": "closing",
			"label": _("Closing", context="RPOS report"),
			"fieldtype": "Link",
			"options": "POS Closing Entry",
			"width": 150,
		},
		{"fieldname": "branch", "label": _("Branch"), "fieldtype": "Link", "options": "Branch", "width": 130},
		{
			"fieldname": "pos_profile",
			"label": _("Terminal", context="RPOS report"),
			"fieldtype": "Link",
			"options": "POS Profile",
			"width": 120,
		},
		{"fieldname": "cashier_name", "label": _("Cashier"), "fieldtype": "Data", "width": 150},
		{"fieldname": "expected", "label": _("Expected"), "fieldtype": "Currency", "width": 110},
		{"fieldname": "counted", "label": _("Counted"), "fieldtype": "Currency", "width": 110},
		{"fieldname": "difference", "label": _("Difference"), "fieldtype": "Currency", "width": 110},
		{"fieldname": "reason", "label": _("Reason"), "fieldtype": "Data", "width": 260},
	]


def _cashier_columns() -> list[dict]:
	return [
		{"fieldname": "cashier_name", "label": _("Cashier"), "fieldtype": "Data", "width": 180},
		{"fieldname": "drawers", "label": _("Drawers"), "fieldtype": "Int", "width": 90},
		{"fieldname": "short_drawers", "label": _("Drawers Short"), "fieldtype": "Int", "width": 110},
		{"fieldname": "short", "label": _("Shortages"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "over", "label": _("Overages"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "net", "label": _("Net"), "fieldtype": "Currency", "width": 120},
	]

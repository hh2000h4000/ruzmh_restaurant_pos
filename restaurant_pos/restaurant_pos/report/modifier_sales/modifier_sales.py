# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Which extras sell, and what they bring in (`D-274`).

«Extra cheese» is added to one burger in three and nobody knows it, because the
invoice carries the burger at its dressed price. This counts every choice on
every line of a settled bill — the free ones too, since «no onion» chosen a
thousand times is worth knowing — and the money each one moved.

**What a choice was worth is what it cost when the line was rung** (`FR-4.2`),
stored on the line, not the option's price today. **Times the line's quantity**:
extra cheese on three burgers is three. **A voided line is not a sale.**

Refs: FR-4.2, FR-11.2, D-274
"""

import json

import frappe
from frappe import _
from frappe.utils import flt

from restaurant_pos.utils import reporting


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date, to_date = reporting.window(filters)

	orders = [row.name for row in reporting.settled_orders(filters, from_date, to_date, ["name"])]
	if not orders:
		return _columns(), []

	choices: dict[tuple, dict] = {}
	for line in frappe.get_all(
		"Restaurant Order Item",
		filters={
			"parenttype": "Restaurant Order",
			"parent": ("in", orders),
			"modifiers": ("is", "set"),
			"status": ("!=", "void"),
		},
		fields=["qty", "modifiers"],
	):
		for choice in _parsed(line.modifiers):
			# A combo's items are sold, not chosen extras; Item Sales counts them (`D-285`).
			if choice.get("item_effect") == "combo":
				continue
			key = (choice.get("group"), choice.get("option"))
			row = choices.setdefault(
				key,
				{
					"group": choice.get("group"),
					"option": choice.get("option_ar") or choice.get("option"),
					"times": 0.0,
					"revenue": 0.0,
				},
			)
			row["times"] += flt(line.qty)
			sign = {"add": 1, "subtract": -1}.get(choice.get("price_effect"), 0)
			row["revenue"] += sign * flt(choice.get("amount")) * flt(line.qty)

	rows = sorted(choices.values(), key=lambda row: (-row["revenue"], -row["times"]))
	for row in rows:
		row["revenue"] = flt(row["revenue"], 2)
	total = {
		"option": _("Total", context="RPOS report"),
		"times": sum(row["times"] for row in rows),
		"revenue": flt(sum(row["revenue"] for row in rows), 2),
	}
	return _columns(), ([*rows, total] if rows else rows)


def _parsed(value) -> list[dict]:
	if not value:
		return []
	try:
		parsed = json.loads(value) if isinstance(value, str) else value
	except ValueError:
		return []
	return parsed if isinstance(parsed, list) else []


def _columns() -> list[dict]:
	return [
		{
			"fieldname": "group",
			"label": _("Modifier Group"),
			"fieldtype": "Link",
			"options": "POS Modifier Group",
			"width": 160,
		},
		{"fieldname": "option", "label": _("Choice"), "fieldtype": "Data", "width": 180},
		{"fieldname": "times", "label": _("Times Chosen"), "fieldtype": "Float", "width": 120},
		{"fieldname": "revenue", "label": _("Revenue"), "fieldtype": "Currency", "width": 120},
	]

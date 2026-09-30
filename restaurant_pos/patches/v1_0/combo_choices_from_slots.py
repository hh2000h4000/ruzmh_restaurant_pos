# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""A combo's choice was typed on each row; it is a record now (`D-290`).

Every name already typed becomes a choice of that name, picking exactly one —
what a typed choice meant until now — so every combo sells as it did.
"""

import frappe


def execute():
	for slot in frappe.get_all(
		"POS Combo Item", filters={"slot": ("is", "set")}, pluck="slot", distinct=True
	):
		if frappe.db.exists("POS Combo Choice", slot):
			continue
		frappe.get_doc(
			{
				"doctype": "POS Combo Choice",
				"title_ar": slot,
				"title": slot,
				"min_selections": 1,
				"max_selections": 1,
			}
		).insert(ignore_permissions=True)

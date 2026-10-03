"""Give the bell's page its default on a site whose settings predate it (`D-301`).

A Single's new field is empty on a site that already had the record, and the
settings page would show 0 — a number the form itself refuses.
"""

import frappe


def execute():
	if not frappe.db.get_single_value("Restaurant POS Settings", "alerts_per_page"):
		frappe.db.set_single_value("Restaurant POS Settings", "alerts_per_page", 20)

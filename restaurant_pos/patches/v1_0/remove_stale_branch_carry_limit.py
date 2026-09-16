# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Remove the carry-over limit field that no code reads any more.

``Branch.max_carried_open_orders`` was a hard limit on how many open bills could
carry into the next day. It was replaced by a warning (``carried_orders_warning_at``,
`D-158`) and dropped from ``install.py`` — but a Custom Field is only ever
created there, never removed, so sites installed before the change still show
the old box on the branch form. A manager reading the form sees two settings for
one question and one of them does nothing.

Idempotent: once the field is gone there is nothing to delete.
"""

import frappe

STALE = "Branch-max_carried_open_orders"


def execute():
	if frappe.db.exists("Custom Field", STALE):
		frappe.delete_doc("Custom Field", STALE, ignore_permissions=True)
		frappe.clear_cache(doctype="Branch")

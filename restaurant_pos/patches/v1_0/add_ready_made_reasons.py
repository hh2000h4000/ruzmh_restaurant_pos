"""Give a site that is already running the ready-made void and cancel reasons (`D-239`).

The starter list runs on install only (`setup/defaults.py` says why), so a
restaurant that installed RPOS before this existed would see an empty row of
chips and keep typing the same four sentences by hand.

Idempotent, and it never argues with a decision: a title that exists is left
alone, and a site that has already written its own reasons for a scope is not
given ours on top.
"""

import frappe

from restaurant_pos.setup.defaults import QUICK_NOTES

SCOPES = ("void_reason", "cancel_reason")


def execute():
	for scope in SCOPES:
		if frappe.db.exists("POS Quick Note", {"scope": scope}):
			continue

		for values in QUICK_NOTES:
			if values["scope"] != scope or frappe.db.exists("POS Quick Note", values["title"]):
				continue

			frappe.get_doc(dict(doctype="POS Quick Note", is_active=1, **values)).insert(
				ignore_permissions=True
			)

	frappe.db.commit()

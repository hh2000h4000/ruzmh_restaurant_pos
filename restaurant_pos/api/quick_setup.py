# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Quick setup from the desk (`D-307`)."""

import frappe
from frappe import _

from restaurant_pos.utils import quick_setup as service


@frappe.whitelist(methods=["POST"])
def run(values: dict | str) -> dict:
	"""Make a branch, its sections and tables, and a terminal, from one form.

	Desk-only, behind the DocTypes' own permissions: everything is inserted as
	the person asking, so somebody who may not create a branch or a terminal is
	refused by ERPNext itself. Asked up front too, so the refusal names the
	reason before anything is half made. One request, one transaction: a
	refusal anywhere leaves nothing behind.
	"""
	for doctype in ("Branch", "Restaurant Section", "Restaurant Table", "POS Profile"):
		if not frappe.has_permission(doctype, "create"):
			frappe.throw(
				_("You may not create a {0}, so quick setup cannot run for you.").format(_(doctype)),
				frappe.PermissionError,
			)
	return service.run(frappe.parse_json(values) if isinstance(values, str) else values)

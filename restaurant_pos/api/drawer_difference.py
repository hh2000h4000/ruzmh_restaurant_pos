# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The accountant's half of a drawer difference (`D-357`)."""

import frappe

from restaurant_pos.utils import drawer_difference as service


@frappe.whitelist(methods=["POST"])
def book(closing_entry: str, account: str | None = None) -> dict:
	"""Book one closing's difference. ERPNext's own rule decides who may: whoever may make a journal entry."""
	frappe.has_permission("Journal Entry", "create", throw=True)
	return {"journal_entry": service.book(closing_entry, account)}


@frappe.whitelist()
def default_account() -> str | None:
	"""The shortage account the dialog starts on."""
	frappe.has_permission("Journal Entry", "create", throw=True)
	return service.default_account()

"""Take the shipped "Corporate" order type and "Credit" method off a site that never used them (`D-320`).

A sale billed to a company is a Sales Invoice in ERPNext, not a till sale. The
two were shipped inactive; a site that switched the type on, rang an order up
on it, or pointed anything at the method keeps what it has.
"""

import frappe


def execute():
	order_type = frappe.db.get_value(
		"Restaurant Order Type",
		{"title": "Corporate", "is_active": 0, "pre_set_customer": ("is", "not set")},
		"name",
	)
	if order_type and not frappe.db.exists("Restaurant Order", {"order_type": order_type}):
		_drop("Restaurant Order Type", order_type)

	if frappe.db.get_value("Mode of Payment", "Credit", "rpos_is_credit") and not frappe.db.exists(
		"Mode of Payment Account", {"parent": "Credit"}
	):
		_drop("Mode of Payment", "Credit")


def _drop(doctype: str, name: str) -> None:
	try:
		frappe.delete_doc(doctype, name, ignore_permissions=True)
	except frappe.LinkExistsError:
		# Something of the restaurant's own points at it: it is theirs now.
		frappe.clear_messages()

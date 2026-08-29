# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Whitelisted customer endpoints.

Thin by design (``02_backend_rules.md``): parse, authorise, delegate to
``utils.customer``, return JSON.

Refs: 07_API_Design.md, FR-2.1 step 4, D-050
"""

import frappe

from restaurant_pos.utils import customer as service
from restaurant_pos.utils import idempotency


@frappe.whitelist()
def search(phone: str | None = None, name: str | None = None) -> list[dict]:
	"""Who this could be — by mobile first, by name only as a fallback."""
	if frappe.session.user == "Guest":
		frappe.throw(frappe._("Sign in first."), frappe.PermissionError)

	return service.search(phone=phone, name=name)


@frappe.whitelist()
def get(customer: str) -> dict:
	"""One customer and their addresses."""
	return service.details(customer)


@frappe.whitelist()
def create(
	phone: str,
	customer_name: str,
	tax_id: str | None = None,
	is_company: int | bool = 0,
	address: dict | str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Make a customer, with the number where ERPNext keeps it (D-050)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	result = service.create(
		phone=phone,
		customer_name=customer_name,
		tax_id=tax_id,
		is_company=bool(int(is_company or 0)),
		address=frappe.parse_json(address) if isinstance(address, str) else address,
	)

	idempotency.remember(
		queue_id, "create_customer", result, reference_doctype="Customer", reference_name=result["name"]
	)
	return result


@frappe.whitelist()
def add_address(customer: str, address: dict | str, queue_id: str | None = None) -> dict:
	"""Another address for a customer who has one already."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	name = service.add_address(customer, frappe.parse_json(address) if isinstance(address, str) else address)
	result = {"address": name, "addresses": service.addresses_of(customer)}

	idempotency.remember(queue_id, "add_address", result, reference_doctype="Address", reference_name=name)
	return result

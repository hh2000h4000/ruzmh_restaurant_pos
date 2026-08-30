# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Whitelisted return endpoints.

Thin by design (``02_backend_rules.md``): parse, authorise, delegate to
``utils.returns``, return JSON.

Refs: 07_API_Design.md, FR-9.1..FR-9.3, BR-050..BR-055, D-064
"""

import frappe

from restaurant_pos.utils import idempotency
from restaurant_pos.utils import returns as service
from restaurant_pos.utils.permissions import validate_branch_access


def _load(order_name: str):
	order = frappe.get_doc("Restaurant Order", order_name)
	validate_branch_access(order.branch)
	return order


@frappe.whitelist()
def get_returnable(order_name: str) -> dict:
	"""What is on a paid bill and how much of it can still come back (FR-9.1)."""
	return service.returnable(_load(order_name))


@frappe.whitelist()
def preview_return(order_name: str, items: list | str) -> dict:
	"""What the refund would come to — read-only, nothing created (FR-9.2 §6)."""
	return service.preview(
		_load(order_name),
		items=frappe.parse_json(items) if isinstance(items, str) else items,
	)


@frappe.whitelist()
def create_return(
	order_name: str,
	items: list | str,
	reason_code: str,
	note: str | None = None,
	refund_method: str | None = None,
	manager_override_token: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Refund part or all of a paid order (FR-9.2).

	Replay-safe like every other write: a refund sent twice because the network
	dropped mid-request would hand the customer their money back twice, which is
	the second most damaging replay in the system after a payment (09 §8).
	"""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	result = service.create_return(
		order,
		items=frappe.parse_json(items) if isinstance(items, str) else items,
		reason_code=reason_code,
		note=note,
		refund_method=refund_method,
		override_token=manager_override_token,
	)

	idempotency.remember(
		queue_id,
		"create_return",
		result,
		reference_doctype="Sales Invoice",
		reference_name=result["credit_note"],
	)
	return result

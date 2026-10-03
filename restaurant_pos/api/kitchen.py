# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Whitelisted kitchen endpoints.

Refs: 07_API_Design.md §3, FR-2.3, FR-2.4, FR-6.3, FR-6.4
"""

import frappe
from frappe import _

from restaurant_pos.utils import idempotency
from restaurant_pos.utils import kitchen as service
from restaurant_pos.utils.order import assert_mutable
from restaurant_pos.utils.permissions import (
	assert_permission,
	validate_branch_access,
)


@frappe.whitelist()
def send_to_kitchen(order_name: str, kot_type: str | None = None, queue_id: str | None = None) -> dict:
	"""Raise a KOT per production center for everything not yet sent (FR-2.3, FR-2.4).

	``kot_type`` is normally left out — the first send is ``initial`` and every
	later one is an ``addition`` (BR-073).
	"""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = frappe.get_doc("Restaurant Order", order_name)
	validate_branch_access(order.branch)
	assert_mutable(order)

	result = service.send_to_kitchen(order, kot_type=kot_type)
	result["status"] = order.status

	idempotency.remember(
		queue_id,
		"send_to_kitchen",
		result,
		reference_doctype="Restaurant Order",
		reference_name=order.name,
	)
	return result


@frappe.whitelist()
def reprint_kot(kot_name: str, queue_id: str | None = None) -> dict:
	"""Queue a ticket to print again (FR-6.4). Logged in the audit trail."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order_name = frappe.db.get_value("Kitchen Order Ticket", kot_name, "restaurant_order")
	if not order_name:
		frappe.throw(_("Kitchen Order Ticket {0} does not exist.").format(kot_name))

	branch = frappe.db.get_value("Restaurant Order", order_name, "branch")
	validate_branch_access(branch)
	assert_permission("can_reprint_receipt")

	result = service.reprint(kot_name)
	idempotency.remember(
		queue_id,
		"reprint_kot",
		result,
		reference_doctype="Kitchen Order Ticket",
		reference_name=kot_name,
	)
	return result


@frappe.whitelist()
def mark_kitchen_told(kot_name: str, queue_id: str | None = None) -> dict:
	"""Say the kitchen was told by hand, so an unprinted ticket stops alerting (`D-298`)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order_name = frappe.db.get_value("Kitchen Order Ticket", kot_name, "restaurant_order")
	if not order_name:
		frappe.throw(_("Kitchen Order Ticket {0} does not exist.").format(kot_name))
	validate_branch_access(frappe.db.get_value("Restaurant Order", order_name, "branch"))

	result = service.mark_kitchen_told(kot_name)
	idempotency.remember(
		queue_id,
		"mark_kitchen_told",
		result,
		reference_doctype="Kitchen Order Ticket",
		reference_name=kot_name,
	)
	return result


@frappe.whitelist()
def get_kots(order_name: str) -> list[dict]:
	"""Every ticket raised for an order, newest first."""
	branch = frappe.db.get_value("Restaurant Order", order_name, "branch")
	if not branch:
		frappe.throw(_("Order {0} does not exist.").format(order_name))

	validate_branch_access(branch)

	return frappe.get_all(
		"Kitchen Order Ticket",
		filters={"restaurant_order": order_name},
		fields=[
			"name",
			"kot_type",
			"production_center",
			"sent_at",
			"printed_at",
			"print_status",
			"printer_used",
		],
		order_by="sent_at desc",
	)

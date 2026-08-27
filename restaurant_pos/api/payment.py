# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Whitelisted payment endpoints.

Replay protection matters more here than anywhere else: a retried payment is a
duplicate invoice, duplicate revenue and a duplicate ZATCA submission.

Refs: 07_API_Design.md §3, FR-2.7, 09 §8
"""

import frappe
from frappe import _
from frappe.utils import flt

from restaurant_pos.utils import idempotency, totals
from restaurant_pos.utils import payment as service
from restaurant_pos.utils.permissions import get_pos_permission_set, validate_branch_access


@frappe.whitelist()
def process_payment(
	order_name: str,
	payments: list | str,
	discount_type: str | None = None,
	discount_value: float = 0,
	promotion_applied: str | None = None,
	loyalty_points_redeemed: float = 0,
	manager_override_token: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Settle an order and submit its Sales Invoice (FR-2.7)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = frappe.get_doc("Restaurant Order", order_name)
	validate_branch_access(order.branch)

	# A second belt against a duplicate invoice: even without a queue_id, an
	# order that is already closed must not be paid again (BR-016).
	if order.sales_invoice:
		frappe.throw(_("Order {0} was already paid — invoice {1}.").format(order.name, order.sales_invoice))

	if flt(loyalty_points_redeemed):
		# FR-10.5 needs the ERPNext Loyalty Program wired through the invoice;
		# refusing is better than silently ignoring a redemption the cashier
		# already promised the customer.
		frappe.throw(_("Loyalty redemption is not available yet."))

	result = service.process_payment(
		order,
		payments=payments,
		discount_type=discount_type,
		discount_value=discount_value,
		promotion_applied=promotion_applied,
		override_token=manager_override_token,
	)

	idempotency.remember(
		queue_id,
		"process_payment",
		result,
		reference_doctype="Restaurant Order",
		reference_name=order.name,
	)
	return result


@frappe.whitelist()
def preview_totals(order_name: str, discount_type: str | None = None, discount_value: float = 0) -> dict:
	"""What the order would come to with this discount, without applying it.

	The payment screen has to show the customer a figure before charging, and
	the frontend never computes money (`CLAUDE.md` §5.1). Nothing is saved: the
	document is loaded, the totals recalculated in memory, and discarded.

	Also reports whether the cashier may apply it, so the UI can ask for a
	manager before the customer is told a price nobody can honour.
	"""
	order = frappe.get_doc("Restaurant Order", order_name)
	validate_branch_access(order.branch)

	order.discount_type = discount_type
	order.discount_value = flt(discount_value)
	totals.calculate(order)

	percentage = service.discount_percentage(order, discount_type, discount_value)
	ceiling = flt(get_pos_permission_set().get(service.CEILING))

	return {
		"subtotal": order.subtotal,
		"discount_amount": order.discount_amount,
		"tax_amount": order.tax_amount,
		"total_amount": order.total_amount,
		"discount_percentage": flt(percentage, 2),
		"max_discount_percentage": ceiling,
		"requires_override": percentage > ceiling,
	}


@frappe.whitelist()
def get_payment_summary(order_name: str) -> dict:
	"""What the payment screen needs: totals and the permitted methods (FR-10.1)."""
	order = frappe.get_doc("Restaurant Order", order_name)
	validate_branch_access(order.branch)

	allowed = frappe.get_all(
		"OT Payment Method",
		filters={"parent": order.order_type, "parenttype": "Restaurant Order Type"},
		fields=["payment_method", "is_forced", "is_default"],
	)

	if not allowed:
		allowed = [
			{"payment_method": row.name, "is_forced": 0, "is_default": 0}
			for row in frappe.get_all("Mode of Payment", filters={"enabled": 1}, fields=["name"])
		]

	return {
		"order_name": order.name,
		"subtotal": order.subtotal,
		"discount_amount": order.discount_amount,
		"tax_amount": order.tax_amount,
		"total_amount": order.total_amount,
		"payment_methods": allowed,
		"already_paid": bool(order.sales_invoice),
		"sales_invoice": order.sales_invoice,
	}

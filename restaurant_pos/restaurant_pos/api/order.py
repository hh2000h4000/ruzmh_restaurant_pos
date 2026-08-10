# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Whitelisted order endpoints.

Thin by design (``02_backend_rules.md``): parse, authorise, delegate to
``utils.order``, return JSON. Every function that changes data is replay-safe
on ``queue_id`` (``09`` §8).

Refs: 07_API_Design.md §3, FR-2.1..FR-2.8
"""

import frappe

from restaurant_pos.restaurant_pos.utils import idempotency
from restaurant_pos.restaurant_pos.utils import order as service
from restaurant_pos.restaurant_pos.utils.permissions import validate_branch_access


def _load(order_name: str):
	order = frappe.get_doc("Restaurant Order", order_name)
	validate_branch_access(order.branch)
	return order


def _summary(order) -> dict:
	return {
		"order_name": order.name,
		"status": order.status,
		"subtotal": order.subtotal,
		"discount_amount": order.discount_amount,
		"tax_amount": order.tax_amount,
		"total_amount": order.total_amount,
		"item_count": len([row for row in order.items if row.status != "void"]),
	}


@frappe.whitelist()
def create_order(
	order_type: str,
	pos_profile: str,
	table: str | None = None,
	customer: str | None = None,
	cover_count: int | None = None,
	waiter: str | None = None,
	order_type_data: dict | None = None,
	notes: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Open an order (FR-2.1)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	existing = (
		frappe.db.get_value("Restaurant Order", {"offline_queue_id": queue_id}, "name") if queue_id else None
	)
	if existing:
		return dict(_summary(frappe.get_doc("Restaurant Order", existing)), already_processed=True)

	order = service.create_order(
		order_type=order_type,
		pos_profile=pos_profile,
		table=table,
		customer=customer,
		cover_count=cover_count,
		waiter=waiter,
		order_type_data=frappe.parse_json(order_type_data)
		if isinstance(order_type_data, str)
		else order_type_data,
		notes=notes,
		offline_queue_id=queue_id,
	)

	result = _summary(order)
	idempotency.remember(
		queue_id,
		"create_order",
		result,
		reference_doctype="Restaurant Order",
		reference_name=order.name,
	)
	return result


@frappe.whitelist()
def add_item(
	order_name: str,
	item: str,
	qty: float = 1,
	modifiers: list | None = None,
	notes: str | None = None,
	course: int | None = None,
	rate: float | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Add a line (FR-2.2).

	``rate`` is ignored unless the caller holds ``can_change_item_price``; the
	price otherwise comes from the price list (``DECISIONS.md`` D-020).
	"""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	row = service.add_item(
		order,
		item=item,
		qty=qty,
		modifiers=frappe.parse_json(modifiers) if isinstance(modifiers, str) else modifiers,
		notes=notes,
		course=course,
		rate=rate,
	)

	result = dict(_summary(order), row_idx=row.idx, rate=row.rate, amount=row.amount)
	idempotency.remember(
		queue_id, "add_item", result, reference_doctype="Restaurant Order", reference_name=order.name
	)
	return result


@frappe.whitelist()
def void_item(
	order_name: str,
	item_idx: int,
	reason: str,
	manager_override_token: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Void a line (FR-2.5)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	outcome = service.void_item(
		order, item_idx=item_idx, reason=reason, override_token=manager_override_token
	)

	result = dict(_summary(order), **outcome)
	idempotency.remember(
		queue_id, "void_item", result, reference_doctype="Restaurant Order", reference_name=order.name
	)
	return result


@frappe.whitelist()
def cancel_order(
	order_name: str,
	reason: str,
	manager_override_token: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Cancel an unpaid order (FR-2.8)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	outcome = service.cancel_order(order, reason=reason, override_token=manager_override_token)

	result = dict(_summary(order), **outcome)
	idempotency.remember(
		queue_id, "cancel_order", result, reference_doctype="Restaurant Order", reference_name=order.name
	)
	return result


@frappe.whitelist()
def get_order(order_name: str) -> dict:
	"""Full order state for the order screen."""
	order = _load(order_name)
	return {
		**_summary(order),
		"order_type": order.order_type,
		"table": order.table,
		"customer": order.customer,
		"cover_count": order.cover_count,
		"opened_at": order.opened_at,
		"items": [
			{
				"idx": row.idx,
				"item": row.item,
				"item_name": row.item_name,
				"qty": row.qty,
				"rate": row.rate,
				"amount": row.amount,
				"status": row.status,
				"notes": row.notes,
				"modifiers": frappe.parse_json(row.modifiers) if row.modifiers else [],
				"production_center": row.production_center,
			}
			for row in order.items
		],
	}

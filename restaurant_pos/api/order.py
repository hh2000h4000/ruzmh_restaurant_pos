# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Whitelisted order endpoints.

Thin by design (``02_backend_rules.md``): parse, authorise, delegate to
``utils.order``, return JSON. Every function that changes data is replay-safe
on ``queue_id`` (``09`` §8).

Refs: 07_API_Design.md §3, FR-2.1..FR-2.8
"""

import frappe
from frappe.utils import now_datetime, time_diff_in_seconds

from restaurant_pos.utils import idempotency
from restaurant_pos.utils import order as service
from restaurant_pos.utils.permissions import validate_branch_access


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


#: An order the cashier can still act on. Anything else belongs to history.
OPEN_STATUSES = ("draft", "active", "in_kitchen", "pending_payment")


@frappe.whitelist()
def get_open_orders(pos_profile: str) -> list[dict]:
	"""Every order still on the floor, for the home screen (06 Screen 1).

	Scoped to the **branch**, not the terminal. An order opened on the waiter's
	tablet has to be payable at the till, and a takeaway opened by the cashier
	who just went on break has to be findable by the one taking over. Scoping
	this to ``pos_profile`` would hide both and strand the order.

	Oldest first: the card that has been waiting longest is the one that needs
	attention (06 §Screen 1 behaviour).
	"""
	# A POS Profile has no branch of its own; it inherits one from the section
	# it serves, the same way `session._profile` resolves it.
	section = frappe.db.get_value("POS Profile", pos_profile, "restaurant_section")
	branch = frappe.db.get_value("Restaurant Section", section, "branch") if section else None

	filters: dict = {"status": ("in", OPEN_STATUSES)}
	if branch:
		validate_branch_access(branch)
		filters["branch"] = branch
	else:
		# A terminal attached to no section has no branch to scope by. Falling
		# back to the terminal is narrower than right; listing every branch's
		# floor would be wrong.
		filters["pos_profile"] = pos_profile

	orders = frappe.get_all(
		"Restaurant Order",
		filters=filters,
		fields=[
			"name",
			"order_type",
			"status",
			"table",
			"cover_count",
			"customer",
			"total_amount",
			"opened_at",
		],
		order_by="opened_at asc",
	)
	if not orders:
		return []

	_annotate_open_orders(orders)
	return orders


def _annotate_open_orders(orders: list) -> None:
	"""Add item count, elapsed minutes and display labels.

	Three lookups for the whole list rather than three per order: a lunch rush
	is fifty open orders and this list refreshes on every realtime event
	(``04`` §8).
	"""
	names = [row.name for row in orders]

	counts: dict[str, int] = {}
	for row in frappe.get_all(
		"Restaurant Order Item",
		filters={"parent": ("in", names), "parenttype": "Restaurant Order"},
		fields=["parent", "status"],
	):
		if row.status != "void":
			counts[row.parent] = counts.get(row.parent, 0) + 1

	# The terminal already holds the order types it is allowed to open, but an
	# order may carry one this terminal cannot open and still needs to display.
	types = {
		row.name: row
		for row in frappe.get_all(
			"Restaurant Order Type",
			filters={"name": ("in", list({row.order_type for row in orders if row.order_type}))},
			fields=["name", "title", "title_ar", "icon", "color"],
		)
	}

	table_numbers = {
		row.name: row.table_number
		for row in frappe.get_all(
			"Restaurant Table",
			filters={"name": ("in", list({row.table for row in orders if row.table}))},
			fields=["name", "table_number"],
		)
	}

	now = now_datetime()
	for order in orders:
		order_type = types.get(order.order_type)
		order.order_type_title = order_type.title if order_type else order.order_type
		order.order_type_title_ar = order_type.title_ar if order_type else order.order_type
		order.icon = order_type.icon if order_type else None
		order.color = order_type.color if order_type else None
		order.table_number = table_numbers.get(order.table)
		order.item_count = counts.get(order.name, 0)
		order.order_minutes = int(time_diff_in_seconds(now, order.opened_at) // 60) if order.opened_at else 0


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

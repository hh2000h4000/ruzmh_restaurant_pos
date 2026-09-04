# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Whitelisted order endpoints.

Thin by design (``02_backend_rules.md``): parse, authorise, delegate to
``utils.order``, return JSON. Every function that changes data is replay-safe
on ``queue_id`` (``09`` §8).

Refs: 07_API_Design.md §3, FR-2.1..FR-2.8
"""

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, now_datetime, nowdate, time_diff_in_seconds

from restaurant_pos.utils import customer as customer_service
from restaurant_pos.utils import idempotency
from restaurant_pos.utils import order as service
from restaurant_pos.utils.permissions import get_pos_permission_set, validate_branch_access


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
	delivery_address: str | None = None,
	cover_count: int | None = None,
	waiter: str | None = None,
	order_type_data: dict | str | None = None,
	notes: str | None = None,
	call_name: str | None = None,
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
		delivery_address=delivery_address,
		cover_count=cover_count,
		waiter=waiter,
		order_type_data=frappe.parse_json(order_type_data)
		if isinstance(order_type_data, str)
		else order_type_data,
		notes=notes,
		call_name=call_name,
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
	modifiers: list | str | None = None,
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
def set_item_qty(
	order_name: str,
	item_idx: int,
	qty: float,
	queue_id: str | None = None,
) -> dict:
	"""Change how many of a line, before it goes to the kitchen (FR-2.2)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	outcome = service.set_item_qty(order, item_idx=item_idx, qty=qty)

	result = dict(_summary(order), **outcome)
	idempotency.remember(
		queue_id, "set_item_qty", result, reference_doctype="Restaurant Order", reference_name=order.name
	)
	return result


@frappe.whitelist()
def set_item_notes(
	order_name: str,
	item_idx: int,
	notes: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Change one line's note (FR-2.9)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	outcome = service.set_item_notes(order, item_idx=item_idx, notes=notes)

	result = dict(_summary(order), **outcome)
	idempotency.remember(
		queue_id, "set_item_notes", result, reference_doctype="Restaurant Order", reference_name=order.name
	)
	return result


@frappe.whitelist()
def remove_item(order_name: str, item_idx: int, queue_id: str | None = None) -> dict:
	"""Take a line off before the kitchen sees it (FR-2.5).

	No reason and no permission: until the ticket prints this is composing an
	order, not withdrawing food.
	"""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	outcome = service.remove_item(order, item_idx=item_idx)

	result = dict(_summary(order), **outcome)
	idempotency.remember(
		queue_id, "remove_item", result, reference_doctype="Restaurant Order", reference_name=order.name
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
def preview_order_type_change(order_name: str, order_type: str) -> dict:
	"""What the bill would become under another order type (D-038).

	Read-only, so it takes no ``queue_id``: the cashier is being shown a figure,
	not committing to it. A total already read out to a customer does not change
	without them hearing it first.
	"""
	return service.preview_order_type_change(_load(order_name), order_type=order_type)


@frappe.whitelist()
def change_order_type(
	order_name: str,
	order_type: str,
	table: str | None = None,
	cover_count: int | None = None,
	order_type_data: dict | str | None = None,
	manager_override_token: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Turn an open order into another type, re-pricing it (D-038).

	Only between two types billed to the customer standing there. An app or
	corporate order is owed by somebody else and is refused in the service layer,
	not here — the same rule has to hold for a queued replay.
	"""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	outcome = service.change_order_type(
		order,
		order_type=order_type,
		table=table,
		cover_count=cover_count,
		order_type_data=frappe.parse_json(order_type_data)
		if isinstance(order_type_data, str)
		else order_type_data,
		override_token=manager_override_token,
	)

	result = dict(_summary(order), **outcome)
	idempotency.remember(
		queue_id,
		"change_order_type",
		result,
		reference_doctype="Restaurant Order",
		reference_name=order.name,
	)
	return result


@frappe.whitelist()
def set_order_table(
	order_name: str,
	table: str,
	cover_count: int | None = None,
	manager_override_token: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Seat an open order at a table, or move it to another one (BR-061).

	Moving an order that already has a table needs ``can_transfer_table`` and is
	audited; seating one that has none is the ordinary flow.
	"""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	outcome = service.seat_order(
		order,
		table=table,
		cover_count=cover_count,
		override_token=manager_override_token,
	)

	result = dict(_summary(order), **outcome)
	idempotency.remember(
		queue_id, "set_order_table", result, reference_doctype="Restaurant Order", reference_name=order.name
	)
	return result


@frappe.whitelist()
def set_order_customer(
	order_name: str,
	customer: str | None = None,
	delivery_address: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Attach a customer to an open order, or change it (FR-2.1 step 4)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	outcome = service.set_customer(order, customer=customer, delivery_address=delivery_address)

	result = dict(_summary(order), **outcome)
	idempotency.remember(
		queue_id,
		"set_order_customer",
		result,
		reference_doctype="Restaurant Order",
		reference_name=order.name,
	)
	return result


@frappe.whitelist()
def set_call_name(
	order_name: str,
	call_name: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Name the order for calling out — not a Customer (FR-2.11)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	outcome = service.set_call_name(order, call_name=call_name)

	result = dict(_summary(order), **outcome)
	idempotency.remember(
		queue_id, "set_call_name", result, reference_doctype="Restaurant Order", reference_name=order.name
	)
	return result


@frappe.whitelist()
def set_order_notes(
	order_name: str,
	notes: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Set the note printed on every station's ticket (FR-2.9)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	outcome = service.set_order_notes(order, notes=notes)

	result = dict(_summary(order), **outcome)
	idempotency.remember(
		queue_id, "set_order_notes", result, reference_doctype="Restaurant Order", reference_name=order.name
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
def preview_split(order_name: str, rows: list | str) -> dict:
	"""What the two bills would come to, before anything moves (FR-2.12).

	Read-only, so no `queue_id`: nothing has happened yet.
	"""
	order = _load(order_name)
	return service.preview_split(order, frappe.parse_json(rows) if isinstance(rows, str) else rows)


@frappe.whitelist()
def split_bill(
	order_name: str,
	rows: list | str,
	cover_count: int | None = None,
	manager_override_token: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Move some lines onto a bill of their own (FR-2.12, BR-067).

	``rows`` is ``[{"idx": 3, "qty": 1}]``; omit ``qty`` to move the whole line.
	"""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	outcome = service.split_order(
		order,
		frappe.parse_json(rows) if isinstance(rows, str) else rows,
		cover_count=cover_count,
		override_token=manager_override_token,
	)

	result = dict(_summary(order), **outcome)
	idempotency.remember(
		queue_id, "split_bill", result, reference_doctype="Restaurant Order", reference_name=order.name
	)
	return result


@frappe.whitelist()
def merge_bills(
	order_name: str,
	into: str,
	manager_override_token: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Put one bill onto another and close the empty one (FR-2.12, BR-067)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	source = _load(order_name)
	target = _load(into)
	outcome = service.merge_orders(source, target, override_token=manager_override_token)

	result = dict(_summary(target), **outcome)
	idempotency.remember(
		queue_id, "merge_bills", result, reference_doctype="Restaurant Order", reference_name=target.name
	)
	return result


#: An order the cashier can still act on. Anything else belongs to history.
OPEN_STATUSES = ("draft", "active", "in_kitchen", "pending_payment")

#: What each tab of the orders pane asks for (06 Screen 3, D-042).
VIEWS = {
	"open": OPEN_STATUSES,
	# A "draft" view was here and is gone on purpose (`D-122`). A draft is an
	# empty bill — the first line makes it active — so the tab filtered to bills
	# with nothing on them, which the card already says in its item count.
	"closed": ("closed", "cancelled"),
	# FR-9, D-070 — the bills money went back out of. A credit note is not a
	# `Restaurant Order`, so it can never appear in a list of orders; what the
	# cashier is actually looking for is **which bill was refunded**, and that is
	# an order. Same card, same list, one more tab.
	"returned": ("closed",),
	"all": (*OPEN_STATUSES, "closed", "cancelled"),
}

#: A day's history is what a till needs — a reprint, a return, "what did table
#: four have". Anything older is a report, and a report is not this list.
CLOSED_LIMIT = 200


@frappe.whitelist()
def list_orders(pos_profile: str, view: str = "open") -> list[dict]:
	"""The orders this till may look at, in one of four views (06 Screen 3).

	Scoped to the **branch**, not the terminal. An order opened on the waiter's
	tablet has to be payable at the till, and a takeaway opened by the cashier
	who just went on break has to be findable by the one taking over. Scoping
	this to ``pos_profile`` would hide both and strand the order.

	Open orders come oldest first: the one that has been waiting longest is the
	one that needs attention (06 §Screen 1 behaviour). History comes newest
	first and only for today, because what a cashier wants from a closed order
	is the one they just closed.
	"""
	statuses = VIEWS.get(view)
	if not statuses:
		frappe.throw(_("Unknown order view {0}.").format(view))

	# A POS Profile has no branch of its own; it inherits one from the section
	# it serves, the same way `session._profile` resolves it.
	section = frappe.db.get_value("POS Profile", pos_profile, "restaurant_section")
	branch = frappe.db.get_value("Restaurant Section", section, "branch") if section else None

	filters: dict = {"status": ("in", statuses)}

	# History is bounded by the day, so the list cannot grow without limit and a
	# cashier is never scrolling through last month to reprint this morning.
	history_only = view in ("closed", "returned")
	if history_only:
		filters["opened_at"] = (">=", get_datetime(f"{nowdate()} 00:00:00"))

	# FR-12.x — whose orders a cashier may see is a permission, enforced here
	# and not by hiding a button. But it scopes **history**, not the floor
	# (`D-121`).
	#
	# It used to scope both, and that was wrong twice over. It contradicted this
	# function's own promise two paragraphs up — that a bill left by the cashier
	# who went on break is findable by the one taking over — and it did not even
	# restrict: the floor plan lists a table's bills without asking, so the
	# cashier tapped table eleven and opened the bill this list had hidden. A
	# rule enforced on one screen and not the other is not a rule.
	#
	# So an open bill in the branch belongs to whoever is working, and the
	# permission decides who may read the day's closed ones.
	mine_only = not get_pos_permission_set().get("can_view_all_orders")
	if mine_only and history_only:
		filters["cashier"] = frappe.session.user

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
			# What the cashier reads on a card and says out loud (FR-2.10).
			"daily_number",
			"call_name",
			"order_type",
			"status",
			"table",
			"cover_count",
			"customer",
			"cashier",
			"sales_invoice",
			"total_amount",
			"opened_at",
		],
		order_by="opened_at desc" if history_only else "opened_at asc",
		limit=CLOSED_LIMIT if history_only else 0,
	)

	# The "all" tab is the one view that mixes the floor with the day's history.
	# Filtering it in the query would have hidden other people's *open* bills
	# too, which is the thing `D-121` set out to stop, so its closed half is
	# dropped here instead.
	if mine_only and not history_only:
		orders = [
			row
			for row in orders
			if row.status not in ("closed", "cancelled") or row.cashier == frappe.session.user
		]

	if not orders:
		return []

	_annotate_refunds(orders)
	if view == "returned":
		orders = [row for row in orders if row.returned_amount]
		if not orders:
			return []

	_annotate_open_orders(orders)
	return orders


def _annotate_refunds(orders: list) -> None:
	"""How much of each bill went back to the customer (FR-9, D-070).

	One query for the whole list, keyed on `return_against` — the same field
	ERPNext links a credit note by. A refunded bill was invisible in the till
	until now: the credit note is not an order, so no list of orders could ever
	show it, and the cashier saw only the sale.
	"""
	invoices = [row.sales_invoice for row in orders if row.get("sales_invoice")]

	refunded: dict[str, float] = {}
	if invoices:
		for row in frappe.get_all(
			"Sales Invoice",
			filters={"return_against": ("in", invoices), "docstatus": 1},
			fields=["return_against", "grand_total"],
		):
			refunded[row.return_against] = refunded.get(row.return_against, 0.0) + abs(flt(row.grand_total))

	for order in orders:
		order.returned_amount = refunded.get(order.get("sales_invoice"), 0.0)


def _annotate_open_orders(orders: list) -> None:
	"""Add item count and display labels.

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

	# The card shows who opened the order, so a cashier taking over a shift can
	# tell their own tables from someone else's at a glance.
	cashiers = {
		row.name: row.full_name
		for row in frappe.get_all(
			"User",
			filters={"name": ("in", list({row.cashier for row in orders if row.cashier}))},
			fields=["name", "full_name"],
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

	for order in orders:
		order_type = types.get(order.order_type)
		order.order_type_title = order_type.title if order_type else order.order_type
		order.order_type_title_ar = order_type.title_ar if order_type else order.order_type
		order.icon = order_type.icon if order_type else None
		order.color = order_type.color if order_type else None
		order.table_number = table_numbers.get(order.table)
		order.cashier_name = cashiers.get(order.cashier) or order.cashier
		order.item_count = counts.get(order.name, 0)


@frappe.whitelist()
def get_order(order_name: str) -> dict:
	"""Full order state for the order screen."""
	order = _load(order_name)
	return {
		**_summary(order),
		"order_type": order.order_type,
		"table": order.table,
		"table_number": frappe.db.get_value("Restaurant Table", order.table, "table_number")
		if order.table
		else None,
		"customer": order.customer,
		"call_name": order.call_name,
		"daily_number": order.daily_number,
		"delivery_address": order.delivery_address,
		# Where it goes, in words. A driver cannot read `ADDR-00012`.
		"delivery_address_line": customer_service.address_label(order.delivery_address),
		"customer_mobile": frappe.db.get_value("Customer", order.customer, "mobile_no")
		if order.customer
		else None,
		# The bill names the customer, and a Customer's id is not their name
		# (06 Screen 3).
		"customer_name": frappe.db.get_value("Customer", order.customer, "customer_name")
		if order.customer
		else None,
		"cover_count": order.cover_count,
		"notes": order.notes,
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

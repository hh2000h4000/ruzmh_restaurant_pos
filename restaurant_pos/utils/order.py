# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Restaurant Order lifecycle.

The business rules of BR-010 to BR-017 and FR-2.1 to FR-2.8 live here; the
whitelisted functions in ``api/order.py`` only authorise and delegate
(``02_backend_rules.md``).

Prices, modifier effects and totals are resolved from the database, never from
the request. The API shape in ``07_API_Design.md`` §3 passes ``rate``, but a
client that can set its own price can sell a burger for one riyal
(``DECISIONS.md`` D-020).

Refs: BR-010..BR-017, BR-024, BR-044, BR-061, FR-2.1..FR-2.8
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from restaurant_pos.utils import kitchen, routing, totals
from restaurant_pos.utils.audit import log_audit
from restaurant_pos.utils.permissions import (
	assert_permission,
	consume_override_token,
	get_pos_permission_set,
	validate_branch_access,
)

#: BR-010. A status not listed as a target cannot be reached from that state.
#:
#: BR-010 draws the happy path ``draft -> active -> in_kitchen ->
#: pending_payment -> closed``, but it is not a chain every order walks.
#: ``FR-2.6`` makes ``pending_payment`` optional — it is set only when the bill
#: preview is printed — and ``FR-2.7`` lets the cashier press Pay straight from
#: the order screen. A takeaway paid at the counter therefore goes
#: ``active -> closed`` without ever touching the two middle states.
TRANSITIONS = {
	"draft": {"active", "in_kitchen", "pending_payment", "cancelled"},
	"active": {"in_kitchen", "pending_payment", "closed", "cancelled"},
	"in_kitchen": {"pending_payment", "closed", "cancelled"},
	"pending_payment": {"in_kitchen", "closed", "cancelled"},
	"closed": set(),
	"cancelled": set(),
}

#: BR-017 — a closed order cannot be modified; a cancelled one is finished.
FINAL_STATES = ("closed", "cancelled")


# --------------------------------------------------------------------------- #
# Guards
# --------------------------------------------------------------------------- #


def assert_mutable(order) -> None:
	"""Raise unless the order may still be changed (BR-017)."""
	if order.status in FINAL_STATES:
		frappe.throw(_("Order {0} is {1} and can no longer be modified.").format(order.name, _(order.status)))


def assert_transition(order, new_status: str) -> None:
	if new_status == order.status:
		return

	if new_status not in TRANSITIONS.get(order.status, set()):
		frappe.throw(_("An order cannot go from {0} to {1}.").format(_(order.status), _(new_status)))


def authorise(action: str, override_token: str | None = None) -> str | None:
	"""Allow ``action`` either by permission or by a manager override.

	Returns the approving user when an override was used, so the caller can
	record it on the audit entry.
	"""
	if get_pos_permission_set().get(action):
		return None

	if not override_token:
		assert_permission(action)  # raises with the standard message

	return consume_override_token(override_token, action)


# --------------------------------------------------------------------------- #
# Creating
# --------------------------------------------------------------------------- #


def create_order(
	*,
	order_type: str,
	pos_profile: str,
	table: str | None = None,
	customer: str | None = None,
	cover_count: int | None = None,
	waiter: str | None = None,
	order_type_data: dict | None = None,
	notes: str | None = None,
	offline_queue_id: str | None = None,
) -> "frappe.Document":
	"""Open a new order (FR-2.1)."""
	profile = _load_profile(pos_profile)
	config = _load_order_type(order_type)

	validate_branch_access(profile.branch)
	_assert_order_type_allowed(config, profile)

	shift = _open_shift_for(profile)

	order = frappe.get_doc(
		{
			"doctype": "Restaurant Order",
			"order_type": order_type,
			"status": "draft",
			"branch": profile.branch,
			"section": profile.restaurant_section,
			"pos_profile": pos_profile,
			"restaurant_shift": shift,
			"cashier": frappe.session.user,
			"waiter": waiter,
			"opened_at": now_datetime(),
			"notes": notes,
			"offline_queue_id": offline_queue_id,
			"is_offline_order": 1 if offline_queue_id else 0,
		}
	)

	_apply_table(order, config, table, profile)
	_apply_customer(order, config, customer)
	_apply_cover_count(order, config, cover_count)
	order.order_type_data = _validated_order_type_data(config, order_type_data, moment="on_open")

	totals.calculate(order)
	order.insert(ignore_permissions=True)

	if order.table:
		set_table_status(order.table, "occupied", order.name)

	return order


def _load_profile(pos_profile: str) -> frappe._dict:
	profile = frappe.db.get_value(
		"POS Profile",
		pos_profile,
		["name", "restaurant_section", "restaurant_shift", "selling_price_list", "currency"],
		as_dict=True,
	)
	if not profile:
		frappe.throw(_("POS Profile {0} does not exist.").format(pos_profile))

	if not profile.restaurant_section:
		frappe.throw(_("POS Profile {0} has no Restaurant Section configured.").format(pos_profile))

	profile.branch = frappe.db.get_value("Restaurant Section", profile.restaurant_section, "branch")
	return profile


def _load_order_type(order_type: str):
	config = frappe.get_cached_doc("Restaurant Order Type", order_type)
	if not config.is_active:
		frappe.throw(_("Order type {0} is not active.").format(config.title))

	return config


def is_order_type_allowed(config, profile, user: str | None = None) -> bool:
	"""BR-003 / FR-1.3 — may this order type be used on this terminal, by this user?

	An empty visibility table means "no restriction", so a fresh install works
	before any branch exists.

	The same rule decides which buttons the home screen shows and whether an
	order may actually be created, so both go through here. If they diverged, a
	cashier would tap a button and be refused.
	"""
	checks = (
		("allowed_branches", "branch", profile.branch),
		("allowed_sections", "section", profile.restaurant_section),
		("allowed_pos_profiles", "pos_profile", profile.name),
	)
	for table_field, row_field, value in checks:
		allowed = [row.get(row_field) for row in config.get(table_field) or []]
		if allowed and value not in allowed:
			return False

	allowed_roles = [row.role for row in config.allowed_roles or []]
	if allowed_roles and not set(allowed_roles) & set(frappe.get_roles(user or frappe.session.user)):
		return False

	return True


def _assert_order_type_allowed(config, profile) -> None:
	if not is_order_type_allowed(config, profile):
		frappe.throw(
			_("Order type {0} is not available here.").format(config.title),
			frappe.PermissionError,
		)


def _open_shift_for(profile) -> str:
	"""BR-044 — no sales without an open shift."""
	shift = profile.restaurant_shift
	if shift and frappe.db.get_value("Restaurant Shift", shift, "status") == "open":
		return shift

	frappe.throw(_("Open a shift before taking orders."))


def _apply_table(order, config, table: str | None, profile) -> None:
	if not config.requires_table:
		order.table = table or None
		return

	if not table:
		frappe.throw(_("Order type {0} requires a table.").format(config.title))

	state = frappe.db.get_value("Restaurant Table", table, ["section", "status", "is_active"], as_dict=True)
	if not state:
		frappe.throw(_("Table {0} does not exist.").format(table))

	if not state.is_active:
		frappe.throw(_("Table {0} is out of service.").format(table))

	if state.section != profile.restaurant_section:
		frappe.throw(_("Table {0} is not in this section.").format(table))

	if state.status not in ("available", "reserved"):
		frappe.throw(_("Table {0} is {1}.").format(table, _(state.status)))

	order.table = table


def _apply_customer(order, config, customer: str | None) -> None:
	if config.customer_mode == "pre_set":
		# BR-002: the order type dictates the customer; the client cannot override.
		order.customer = config.pre_set_customer
		return

	if config.customer_mode == "required" and not customer:
		frappe.throw(_("Order type {0} requires a customer.").format(config.title))

	order.customer = customer


def _apply_cover_count(order, config, cover_count) -> None:
	"""BR-064 — cover count is mandatory for dine-in when configured."""
	if config.requires_cover_count and cint(cover_count) < 1:
		frappe.throw(_("Enter the number of guests."))

	order.cover_count = cint(cover_count)


def _validated_order_type_data(config, data: dict | None, *, moment: str) -> dict:
	"""FR-1.2 — the order type's additional fields."""
	data = dict(data or {})
	for row in config.additional_fields or []:
		if row.show_at not in (moment, "both"):
			continue

		value = data.get(row.field_label)
		if row.is_required and (value is None or str(value).strip() == ""):
			frappe.throw(_("{0} is required.").format(row.field_label))

		if value is not None and row.field_type == "select":
			options = [line.strip() for line in (row.field_options or "").splitlines() if line.strip()]
			if options and str(value) not in options:
				frappe.throw(_("{0} must be one of: {1}").format(row.field_label, ", ".join(options)))

	return data


# --------------------------------------------------------------------------- #
# Items
# --------------------------------------------------------------------------- #


def add_item(
	order,
	*,
	item: str,
	qty: float = 1,
	modifiers: list | None = None,
	notes: str | None = None,
	course: int | None = None,
	rate: float | None = None,
) -> "frappe.Document":
	"""Add a line to an open order (FR-2.2)."""
	assert_mutable(order)

	if flt(qty) <= 0:
		frappe.throw(_("Quantity must be greater than zero."))

	details = _load_item(item)
	resolved_modifiers, modifier_delta = _resolve_modifiers(item, modifiers)
	unit_rate = _resolve_rate(order, item, rate)

	route = routing.resolve_route(
		item,
		branch=order.branch,
		order_type=order.order_type,
		pos_profile=order.pos_profile,
	)

	row = order.append(
		"items",
		{
			"item": item,
			"item_name": details.pos_display_name_ar or details.item_name,
			"item_name_en": details.item_name,
			"qty": flt(qty),
			"rate": unit_rate,
			"amount": totals.line_amount(unit_rate, qty, modifier_delta),
			# Frappe's JSON fieldtype rejects a Python list; it stores text.
			"modifiers": frappe.as_json(resolved_modifiers) if resolved_modifiers else None,
			"notes": notes,
			"course": cint(course),
			"production_center": route.production_center,
			"status": "pending",
		},
	)

	if order.status == "draft":
		order.status = "active"

	totals.calculate(order)
	order.save(ignore_permissions=True)
	return row


def _load_item(item: str) -> frappe._dict:
	details = frappe.db.get_value(
		"Item", item, ["name", "item_name", "pos_display_name_ar", "disabled"], as_dict=True
	)
	if not details:
		frappe.throw(_("Item {0} does not exist.").format(item))

	if details.disabled:
		frappe.throw(_("Item {0} is disabled.").format(details.item_name))

	return details


def price_list_for(order_type: str | None, pos_profile: str) -> str | None:
	"""Which price list an order of this type sells from (FR-1.6).

	The order type wins when it names one. A delivery platform takes a
	commission, so its menu is priced above the dining room's, and the shop
	needs to say that once on the order type rather than per item.

	The terminal's own list is the fallback, which is what every order type used
	before this existed.
	"""
	listed = None
	if order_type:
		listed = frappe.db.get_value("Restaurant Order Type", order_type, "selling_price_list")

	return listed or frappe.db.get_value("POS Profile", pos_profile, "selling_price_list")


def _resolve_rate(order, item: str, requested_rate: float | None) -> float:
	"""The selling price, from the price list — not from the client.

	A caller may override only with ``can_change_item_price``, and the override
	is audited (``price_change``, 08 §5).

	A *missing* price is refused rather than treated as zero. Silently selling
	at zero because nobody configured a price is a hole that only shows up in
	the day's takings. A price list row that says ``0`` is a deliberate free
	item and is honoured.
	"""
	price_list = price_list_for(order.order_type, order.pos_profile)
	if not price_list:
		frappe.throw(_("POS Profile {0} has no selling price list.").format(order.pos_profile))

	listed = frappe.db.get_value(
		"Item Price",
		{"item_code": item, "price_list": price_list, "selling": 1},
		"price_list_rate",
	)

	if listed is None:
		if requested_rate is None:
			frappe.throw(_("No price is configured for {0} in price list {1}.").format(item, price_list))
		listed = 0.0

	listed = flt(listed)

	if requested_rate is None or flt(requested_rate) == listed:
		return totals.money(listed)

	assert_permission("can_change_item_price")

	if flt(requested_rate) < 0:
		frappe.throw(_("A price cannot be negative."))

	log_audit(
		"price_change",
		branch=order.branch,
		pos_profile=order.pos_profile,
		restaurant_order=order.name,
		details={"item": item, "listed_rate": listed, "charged_rate": flt(requested_rate)},
	)
	return totals.money(requested_rate)


def _resolve_modifiers(item: str, selected: list | None) -> tuple[list, float]:
	"""Price each selected modifier from the database (FR-4.2).

	The client sends which options were chosen; what they cost is read here. A
	client-supplied price effect is a free lunch.
	"""
	if not selected:
		return [], 0.0

	allowed_groups = {
		row.modifier_group
		for row in frappe.get_all(
			"Modifier Group Assignment",
			filters={"parent": item, "parenttype": "Item"},
			fields=["modifier_group"],
		)
	}

	resolved, delta = [], 0.0
	for choice in selected:
		group = choice.get("group")
		option_title = choice.get("option")

		if allowed_groups and group not in allowed_groups:
			frappe.throw(_("Modifier group {0} does not apply to this item.").format(group))

		option = frappe.db.get_value(
			"POS Modifier Option",
			{"parent": group, "title": option_title, "is_active": 1},
			["title", "title_ar", "price_effect", "price_amount"],
			as_dict=True,
		)
		if not option:
			frappe.throw(_("Modifier option {0} is not available.").format(option_title))

		effect = flt(option.price_amount)
		if option.price_effect == "add":
			delta += effect
		elif option.price_effect == "subtract":
			delta -= effect
		elif option.price_effect == "replace":
			delta += effect

		resolved.append(
			{
				"group": group,
				"option": option.title,
				"option_ar": option.title_ar,
				"price_effect": option.price_effect,
				"amount": effect,
			}
		)

	return resolved, delta


def void_item(order, *, item_idx: int, reason: str, override_token: str | None = None) -> dict:
	"""Void one line (FR-2.5, BR-013)."""
	assert_mutable(order)

	if not (reason or "").strip():
		frappe.throw(_("A reason is required to void an item."))

	approved_by = authorise("can_void_item", override_token)

	row = next((line for line in order.items if line.idx == cint(item_idx)), None)
	if not row:
		frappe.throw(_("Row #{0} is not on this order.").format(item_idx))

	if row.status == "void":
		frappe.throw(_("Row #{0} is already voided.").format(item_idx))

	was_sent = row.status == "sent"

	row.status = "void"
	row.void_reason = reason
	row.voided_by = frappe.session.user
	row.voided_at = now_datetime()

	totals.calculate(order)
	order.save(ignore_permissions=True)

	log_audit(
		"void_item",
		branch=order.branch,
		pos_profile=order.pos_profile,
		restaurant_order=order.name,
		approved_by=approved_by,
		reason=reason,
		details={
			"item": row.item,
			"item_name": row.item_name,
			"qty": flt(row.qty),
			"amount": flt(row.amount),
			"was_sent_to_kitchen": was_sent,
		},
	)

	# BR-013 — a line the kitchen already has must be withdrawn on paper too.
	void_kots = kitchen.create_void_kot(order, [row]) if was_sent else []

	return {"voided": row.idx, "void_kots": void_kots}


# --------------------------------------------------------------------------- #
# Cancelling
# --------------------------------------------------------------------------- #


def cancel_order(order, *, reason: str, override_token: str | None = None) -> dict:
	"""Cancel an unpaid order (FR-2.8, BR-014)."""
	if order.status == "closed":
		frappe.throw(_("A paid order cannot be cancelled. Create a return instead."))

	if order.status == "cancelled":
		frappe.throw(_("Order {0} is already cancelled.").format(order.name))

	if not (reason or "").strip():
		frappe.throw(_("A reason is required to cancel an order."))

	approved_by = authorise("can_cancel_order", override_token)

	# Captured before the status change, so the kitchen still knows what it was
	# given (FR-2.8).
	sent_rows = [row for row in order.items if row.status == "sent"]

	assert_transition(order, "cancelled")
	order.status = "cancelled"
	order.cancel_reason = reason
	order.cancelled_by = frappe.session.user
	order.closed_at = now_datetime()
	order.save(ignore_permissions=True)

	if order.table:
		set_table_status(order.table, "available", None)

	void_kots = kitchen.create_void_kot(order, sent_rows)

	log_audit(
		"cancel_order",
		branch=order.branch,
		pos_profile=order.pos_profile,
		restaurant_order=order.name,
		approved_by=approved_by,
		reason=reason,
		details={"sent_items": len(sent_rows), "total_amount": flt(order.total_amount)},
	)

	return {"cancelled": order.name, "void_kots": void_kots}


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #


def set_table_status(table: str, status: str, order_name: str | None) -> None:
	"""Update a table and tell every terminal in the branch (BR-061, note 4)."""
	frappe.db.set_value(
		"Restaurant Table", table, {"status": status, "current_order": order_name}, update_modified=False
	)

	branch = frappe.db.get_value(
		"Restaurant Section",
		frappe.db.get_value("Restaurant Table", table, "section"),
		"branch",
	)

	frappe.publish_realtime(
		event="rpos:table_update",
		message={"table": table, "status": status, "order": order_name},
		room=f"rpos:branch:{branch}",
	)

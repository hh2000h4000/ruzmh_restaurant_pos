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

from restaurant_pos.utils import (
	activity,
	addons,
	availability,
	combos,
	kitchen,
	numbering,
	routing,
	terminal_branch,
	totals,
)
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
	"""Raise unless the order may still be changed (BR-017, BR-044).

	Two conditions, and the second one is new (D-058):

	1. The order is not already closed or cancelled.
	2. **A shift is open on this terminal.** Adding, editing, removing, sending
	   to the kitchen, paying, cancelling — every one of them already comes
	   through here, so the shift gate lives here rather than being remembered
	   at a dozen call sites. Remembering it twelve times is how eleven of them
	   get it and the twelfth becomes the hole somebody finds.

	Reading and printing do not call this, which is exactly the line drawn: with
	no shift open a cashier may look at yesterday's bills and change nothing.
	"""
	if order.status in FINAL_STATES:
		frappe.throw(_("Order {0} is {1} and can no longer be modified.").format(order.name, _(order.status)))

	# Lazy: `shift` reads `payment`, and `payment` reads this module.
	from restaurant_pos.utils import shift as shift_service

	shift_service.assert_may_sell(order.pos_profile)


# `assert_order_day_open` was here, and is deliberately gone (`D-105`).
#
# It refused to add items to a draft whose own day had since closed. That was
# the wrong place for the rule: an open bill is a bill, and a restaurant may
# well carry one across midnight — a tab that runs late, or a numbered bill
# emptied and reused for the next customer, because not every open bill belongs
# to somebody who comes back.
#
# The constraint belongs at the *other* end, and is now a branch setting:
# `close_open_orders_with_day` decides whether the day may end while bills are
# still open. `assert_mutable` still requires an open till, so the hole that
# started all this — paying a held draft with no shift open — stays closed.


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
	delivery_address: str | None = None,
	cover_count: int | None = None,
	waiter: str | None = None,
	order_type_data: dict | None = None,
	notes: str | None = None,
	call_name: str | None = None,
	offline_queue_id: str | None = None,
) -> "frappe.Document":
	"""Open a new order (FR-2.1)."""
	profile = _load_profile(pos_profile)
	config = _load_order_type(order_type)

	validate_branch_access(profile.branch)

	# The hall comes from the table, so it has to be known before the order type
	# is judged: a type restricted to the family hall must be allowed on a till
	# that sits in the men's hall but is seating a family table (D-040).
	section = section_of_table(table, profile)
	_assert_order_type_allowed(config, profile, section)

	shift = assert_shift_open(profile.restaurant_shift, pos_profile=profile.name)

	order = frappe.get_doc(
		{
			"doctype": "Restaurant Order",
			"order_type": order_type,
			"status": "draft",
			"branch": profile.branch,
			"section": section,
			"pos_profile": pos_profile,
			"restaurant_shift": shift,
			"cashier": frappe.session.user,
			"waiter": waiter,
			# A name to call across a counter, not a Customer record (FR-2.11).
			"call_name": (call_name or "").strip() or None,
			# The short number the customer is told, restarted on the branch's
			# own cycle. `name` stays the permanent id (FR-2.10).
			"daily_number": numbering.next_order_number(branch=profile.branch, shift=shift),
			"opened_at": now_datetime(),
			"notes": notes,
			"offline_queue_id": offline_queue_id,
			"is_offline_order": 1 if offline_queue_id else 0,
		}
	)

	_apply_table(order, config, table, profile)
	_apply_customer(order, config, customer)
	_apply_address(order, delivery_address)
	_apply_cover_count(order, config, cover_count)
	order.order_type_data = _validated_order_type_data(config, order_type_data, moment="on_open")

	totals.calculate(order)
	order.insert(ignore_permissions=True)

	if order.table:
		set_table_status(order.table, "occupied", order.name)

	activity.log(
		order,
		"opened",
		subject=config.title_ar or config.title,
		details={"order_type": order_type, "table": order.table, "daily_number": order.daily_number},
	)

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

	profile.branch = terminal_branch.branch_of(pos_profile)
	if not profile.branch:
		frappe.throw(_("POS Profile {0} has no Restaurant Section configured.").format(pos_profile))
	return profile


def _load_order_type(order_type: str):
	config = frappe.get_cached_doc("Restaurant Order Type", order_type)
	if not config.is_active:
		frappe.throw(_("Order type {0} is not active.").format(config.title))

	return config


def is_order_type_allowed(config, profile, section: str | None = None, user: str | None = None) -> bool:
	"""BR-003 / FR-1.3 — may this order type be used on this terminal, by this user?

	An empty visibility table means "no restriction", so a fresh install works
	before any branch exists.

	``section`` is the hall the order will actually sit in — the table's, not the
	terminal's, once one has been picked (D-040). It falls back to the terminal's
	own hall, which is what the home screen has to judge by before any table is
	chosen.

	The same rule decides which buttons the home screen shows and whether an
	order may actually be created, so both go through here. If they diverged, a
	cashier would tap a button and be refused.
	"""
	checks = (
		("allowed_branches", "branch", profile.branch),
		("allowed_sections", "section", section or profile.restaurant_section),
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


def _assert_order_type_allowed(config, profile, section: str | None = None) -> None:
	if not is_order_type_allowed(config, profile, section):
		frappe.throw(
			_("Order type {0} is not available here.").format(config.title),
			frappe.PermissionError,
		)


def assert_shift_open(shift: str | None, *, pos_profile: str) -> str:
	"""BR-044 — the one place that decides a terminal may sell.

	Two things have to be true, and both are checked every time:

	1. **The day is open.** The terminal's before an order exists, and the
	   order's own before anything more goes on the bill — a bill that kept
	   growing after the day closed would leave the report short by whatever was
	   rung up after the count.
	2. **A drawer is open for this cashier.** Closing a till hands the money back
	   and counts it while the day carries on for whoever is next; a sale after
	   that count belongs to no drawer, and a shortage stops being traceable to
	   anybody (D-054).

	One message for both, because one button fixes both: opening a till opens
	the day too when nobody has.
	"""
	# Imported here, not at the top: `shift` reads `payment`, and `payment`
	# reads this module. A real cycle, and one lazy import is cheaper than
	# splitting a module to break it.
	from restaurant_pos.utils import shift as shift_service

	shift_service.assert_may_sell(pos_profile)

	# And the bill's own day, which is not the same question: a draft held over
	# from a day that has since closed does not resume taking items just because
	# somebody opened today's (D-055).
	if shift and frappe.db.get_value("Restaurant Shift", shift, "status") == "open":
		return shift

	frappe.throw(_("Open a shift before taking orders."))


def _apply_table(order, config, table: str | None, profile) -> None:
	if not config.requires_table:
		order.table = table or None
		return

	if not table:
		frappe.throw(_("Order type {0} requires a table.").format(config.title))

	assert_table_free(table, profile.branch)
	order.table = table


def assert_table_free(table: str, branch: str | None) -> frappe._dict:
	"""Raise unless this table exists, works, and can take an order right now.

	Shared by the two ways an order reaches a table — created at one, or seated
	at one later (``seat_order``) — because a rule enforced in one place and not
	the other is how two orders end up on table four.

	**The table's row is locked while it is asked** (`D-355`). Two tills tapping
	the same free table in the same instant both read "available" and both
	opened a bill — measured, two requests 0.2 s apart. Locked, the second waits
	for the first to commit and then reads "occupied". The lock lasts the
	request, a few milliseconds, and only on the one table.
	"""
	state = frappe.db.get_value(
		"Restaurant Table",
		table,
		["section", "status", "is_active", "capacity", "table_number"],
		as_dict=True,
		for_update=True,
	)
	if not state:
		frappe.throw(_("Table {0} does not exist.").format(table))

	if not state.is_active:
		frappe.throw(_("Table {0} is out of service.").format(table))

	# The **branch**, not the terminal's own hall. A restaurant with a men's
	# hall and a family hall often runs one till at the door for both, and
	# refusing every table outside the terminal's section would force a second
	# terminal on it for no reason (D-040).
	if table_section_branch(state.section) != branch:
		frappe.throw(_("Table {0} is not in this branch.").format(table))

	if state.status in ("available", "reserved"):
		return state

	# A second bill on a table that already has one, when the restaurant allows
	# it (`BR-066`). Two couples on a large table, or a group that asked to be
	# billed separately from the start — ordinary in some restaurants and an
	# error in others, so it is the restaurant's setting and it is off by
	# default. A till that quietly opened a second bill on table four would turn
	# one party into two, and the mistake surfaces when somebody pays half of it.
	if state.status == "occupied" and allows_second_bill(branch):
		return state

	# The number the cashier sees on the floor and the status in their language —
	# not the record's name and an English word, which is what this said.
	frappe.throw(
		_("Table {0} is {1}.").format(
			state.table_number or table, _(state.status, context="Restaurant Table")
		)
	)


def table_section_branch(section: str | None) -> str | None:
	return frappe.db.get_value("Restaurant Section", section, "branch") if section else None


def branch_of_profile(pos_profile: str | None) -> str | None:
	"""Which branch a terminal belongs to: `terminal_branch.branch_of` (`D-393`)."""
	return terminal_branch.branch_of(pos_profile)


def profiles_in(branch: str) -> list[str]:
	"""The terminals of one branch: `terminal_branch.terminals_in` (`D-393`)."""
	return terminal_branch.terminals_in(branch)


def section_of_table(table: str | None, profile) -> str | None:
	"""Which hall an order belongs to.

	The table decides it when there is one; the terminal's own section is only
	the fallback for an order that never sits down (D-040).
	"""
	if table:
		return frappe.db.get_value("Restaurant Table", table, "section") or profile.restaurant_section
	return profile.restaurant_section


def _apply_customer(order, config, customer: str | None) -> None:
	if config.customer_mode == "pre_set":
		# BR-002: the order type dictates the customer; the client cannot override.
		order.customer = config.pre_set_customer
		return

	if config.customer_mode == "required" and not customer:
		frappe.throw(_("Order type {0} requires a customer.").format(config.title))

	order.customer = customer


def _apply_address(order, delivery_address: str | None) -> None:
	"""Where the order goes, when it goes anywhere (FR-2.1 step 4).

	Checked against the customer it belongs to: an address linked to somebody
	else is either a mistake or a way to read a stranger's home.
	"""
	if not delivery_address:
		order.delivery_address = None
		return

	if not order.customer:
		frappe.throw(_("An address needs a customer."))

	owned = frappe.get_all(
		"Dynamic Link",
		filters={
			"parent": delivery_address,
			"parenttype": "Address",
			"link_doctype": "Customer",
			"link_name": order.customer,
		},
		limit=1,
	)
	if not owned:
		frappe.throw(_("That address does not belong to this customer."))

	order.delivery_address = delivery_address


def set_customer(order, *, customer: str | None, delivery_address: str | None = None) -> dict:
	"""Attach a customer, or change which one (FR-2.1 step 4).

	Editable after the order opens because a cashier rings items first and asks
	for the number while the food is being made — and a delivery type that could
	only be given a customer at creation would have to be cancelled and rung
	again when the number came out wrong.
	"""
	assert_mutable(order)

	config = frappe.get_cached_doc("Restaurant Order Type", order.order_type)

	if not customer and config.customer_mode == "required":
		frappe.throw(_("Order type {0} needs a customer.").format(config.title))

	if config.customer_mode == "pre_set":
		frappe.throw(
			_("Order type {0} decides its own customer.").format(config.title),
			frappe.ValidationError,
		)

	if customer and not frappe.db.exists("Customer", customer):
		frappe.throw(_("Customer {0} does not exist.").format(customer))

	order.customer = customer or None
	_apply_address(order, delivery_address if customer else None)
	order.save(ignore_permissions=True)

	return {"customer": order.customer, "delivery_address": order.delivery_address}


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
	join: bool = False,
) -> "frappe.Document":
	"""Add a line to an open order (FR-2.2).

	``join`` is the cashier's add (`D-352`): the same thing asked for again
	raises the line that is already there instead of making a second one. A
	replay of what a device sold offline leaves it off — the bill it rebuilds
	has the lines the cashier saw.
	"""
	assert_mutable(order)
	# BR-044 — the bill stops growing when the shift it belongs to closes.

	if flt(qty) <= 0:
		frappe.throw(_("Quantity must be greater than zero."))

	details = _load_item(item)
	# `D-321` — a branch that enforces its stock refuses the bottle it has not got.
	availability.assert_can_sell(order, item, qty)
	resolved_modifiers, modifier_delta = _resolve_modifiers(
		item, modifiers, price_list_for(order.order_type, order.pos_profile)
	)
	_assert_addons_in_stock(order, resolved_modifiers, qty)
	unit_rate = _resolve_rate(order, item, rate)

	route = routing.resolve_route(
		item,
		branch=order.branch,
		order_type=order.order_type,
		pos_profile=order.pos_profile,
	)

	row = (
		_same_line(
			order,
			item=item,
			rate=unit_rate,
			modifiers=resolved_modifiers,
			notes=notes,
			course=course,
			production_center=route.production_center,
		)
		if join
		else None
	)

	if row:
		row.qty = flt(row.qty) + flt(qty)
		row.amount = totals.line_amount(unit_rate, row.qty, modifier_delta)
	else:
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

	activity.log(
		order,
		"item_added",
		subject=f"{flt(qty):g} x {row.item_name}",
		details={"item": item, "qty": flt(qty), "rate": unit_rate, "amount": row.amount},
	)

	return row


def _same_line(order, *, item, rate, modifiers, notes, course, production_center):
	"""The line a second ask for the same thing belongs on, if there is one (`D-352`).

	**Only a line the kitchen has not been given.** Raising a sent line would
	leave the kitchen cooking one and the customer paying for two — the reason
	`set_item_qty` refuses it — so the second one after a send is a line of its
	own, and goes out on the next ticket like anything else added late.

	And only a line that is the same in everything a cashier or a cook can see:
	the price, the options, the note, the course, the station. Two burgers, one
	without onion, are two lines.
	"""
	for line in order.items:
		if (
			line.status == "pending"
			and line.item == item
			and flt(line.rate) == flt(rate)
			and (line.notes or "") == (notes or "")
			and cint(line.course) == cint(course)
			and (line.production_center or "") == (production_center or "")
			and frappe.parse_json(line.modifiers or "[]") == (modifiers or [])
		):
			return line

	return None


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
	if is_open_price(item):
		return _open_price(item, requested_rate)

	price_list = price_list_for(order.order_type, order.pos_profile)
	if not price_list:
		frappe.throw(_("POS Profile {0} has no selling price list.").format(order.pos_profile))

	listed = _price_on(item, price_list)

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


def is_open_price(item: str) -> bool:
	"""Whether the shop prices this dish at the counter (`D-378`)."""
	return bool(frappe.get_cached_value("Item", item, "rpos_open_price"))


def _open_price(item: str, requested_rate: float | None) -> float:
	"""The price the cashier typed, for a dish the shop marked «open price».

	**No permission is asked** (`D-378`), as on Toast: the manager decided when
	marking the item that its price is said at the counter, so typing it is the
	sale, not an exception to it. Changing the price of a *fixed* item stays
	behind ``can_change_item_price``.

	Nothing is refused for being unusual, only for being no price: missing, zero
	or below. A zero would sell the dish for nothing with no line saying so —
	a free dish is a promotion or a price list row of 0, both of which leave a
	trace.
	"""
	if requested_rate is None:
		frappe.throw(_("Type the price of {0}.").format(_item_name(item)))
	if flt(requested_rate) <= 0:
		frappe.throw(_("The price of {0} must be more than zero.").format(_item_name(item)))
	return totals.money(requested_rate)


def _item_name(item: str) -> str:
	return frappe.get_cached_value("Item", item, "item_name") or item


def _resolve_modifiers(item: str, selected: list | None, price_list: str | None = None) -> tuple[list, float]:
	"""Price each selected modifier from the database (FR-4.2).

	The client sends which options were chosen; what they cost is read here. A
	client-supplied price effect is a free lunch.

	**`item_price` is the linked item's own price on this order's list**
	(`D-284`), stored as the `add` it amounts to — so everything downstream of
	the order line reads one kind of surcharge.
	"""
	# `D-285` — a combo's choices are its items, and it has no others.
	if combos.is_combo(item):
		return combos.resolve(item, selected, price_list)

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
			["title", "title_ar", "price_effect", "price_amount", "stock_item", "stock_qty", "item_effect"],
			as_dict=True,
		)
		if not option:
			frappe.throw(_("Modifier option {0} is not available.").format(option_title))

		if option.price_effect == "item_price":
			option.price_effect = "add"
			option.price_amount = addons.portion_price(option.stock_item, option.stock_qty, price_list)
			if option.price_amount is None:
				frappe.throw(
					_("{0} takes its price from {1}, which has no price in {2}.").format(
						option.title_ar or option.title, option.stock_item, price_list
					)
				)

		effect = flt(option.price_amount)
		if option.price_effect == "add":
			delta += effect
		elif option.price_effect == "subtract":
			delta -= effect

		choice = {
			"group": group,
			"option": option.title,
			"option_ar": option.title_ar,
			"price_effect": option.price_effect,
			"amount": effect,
		}
		# `D-284` — kept with the line like the price, so an option edited later
		# does not change what an earlier order sells or takes out of stock.
		if option.stock_item:
			choice["item"] = option.stock_item
			choice["item_effect"] = option.item_effect
			choice["item_qty"] = flt(option.stock_qty) or 1
		resolved.append(choice)

	return resolved, delta


def _assert_addons_in_stock(order, choices: list, more: float) -> None:
	"""An add-on sold as a stock item is a thing sold as it came (`D-335`).

	Extra cheese is a slice of cheese off the shelf, sold on a line of its own
	(`D-284`) — so an enforcing branch refuses it like the bottle of water,
	and it went unasked: the owner's trial sold one with the cheese at minus
	fourteen. The dish it sits on is still never refused for its recipe.

	Best effort like the rest (`docs/14` §5.0): add-ons on bills still open are
	not counted against the shelf, only those already sold.

	**And a combo's choice** (`D-358`). The cola in the meal is the cola off the
	shelf, and it was sold unasked: the two-till round sold a Pepsi inside a combo
	with none left, on a branch that enforces. A choice that is a dish passes,
	as the dish does on its own — it is not kept in stock as itself.
	"""
	for choice in choices or []:
		if choice.get("item") and choice.get("item_effect") in ("sell", combos.EFFECT):
			availability.assert_can_sell(
				order, choice["item"], flt(more) * (flt(choice.get("item_qty")) or 1)
			)


def set_item_qty(order, *, item_idx: int, qty: float) -> dict:
	"""Change a line's quantity, before the kitchen has it (FR-2.2).

	**Only a line still ``pending``.** Once a ticket is printed, quietly
	changing the number would leave the kitchen cooking one thing and the
	customer paying for another; the way to reduce a sent line is a void, which
	withdraws it on paper too (BR-013).

	Not audited, deliberately: adding a line is not audited either, and this is
	the same act — arranging an order nobody has acted on yet. What is audited
	is the moment that stops being true, which is the void.
	"""
	assert_mutable(order)
	# BR-044 — raising a quantity is adding food, and it obeys the same rule.

	if flt(qty) <= 0:
		frappe.throw(_("Quantity must be greater than zero."))

	row = next((line for line in order.items if line.idx == cint(item_idx)), None)
	if not row:
		frappe.throw(_("Row #{0} is not on this order.").format(item_idx))

	if row.status != "pending":
		frappe.throw(
			_("Row #{0} has already gone to the kitchen. Void it instead.").format(item_idx),
			frappe.ValidationError,
		)

	before = flt(row.qty)
	availability.assert_can_sell(order, row.item, flt(qty) - before)
	_assert_addons_in_stock(order, addons.chosen(row.modifiers), flt(qty) - before)

	# The modifiers were priced when the line was added, and re-resolving them
	# now would silently re-price the options at today's amounts. Recover the
	# per-unit delta from what was stored instead.
	delta_per_unit = (flt(row.amount) / before) - flt(row.rate) if before else 0.0

	row.qty = flt(qty)
	row.amount = totals.line_amount(flt(row.rate), qty, delta_per_unit)

	totals.calculate(order)
	order.save(ignore_permissions=True)

	activity.log(
		order,
		"item_qty_changed",
		subject=f"{row.item_name}: {before:g} → {flt(row.qty):g}",
		details={"item": row.item, "from": before, "to": flt(row.qty)},
	)

	return {"item_idx": row.idx, "qty": flt(row.qty), "amount": flt(row.amount)}


def remove_item(order, *, item_idx: int) -> dict:
	"""Take a line off an order the kitchen has not seen (FR-2.5).

	**No reason, no permission, no trail.** A cashier taps rice, the customer
	says bulgur, or the finger lands one button over — and until the ticket is
	printed that is not a void, it is composing an order nobody has acted on.
	Demanding a written reason for a mis-tap costs seconds at every till in the
	shop and teaches cashiers to type "x" to get past the box, which is worse
	than no reason at all.

	The same reasoning as ``set_item_qty``: adding a line is not audited either,
	and this is the same act. What *is* audited is the moment that stops being
	true — the line reaching a station — and from there it is ``void_item``.
	"""
	assert_mutable(order)
	# BR-044 — the cart is the cart. Taking a line off changes the total as
	# surely as adding one does, and a bill that shrank after its shift was
	# counted is a shortfall nobody can trace (D-056).

	row = next((line for line in order.items if line.idx == cint(item_idx)), None)
	if not row:
		frappe.throw(_("Row #{0} is not on this order.").format(item_idx))

	if row.status != "pending":
		frappe.throw(
			_("Row #{0} has already gone to the kitchen. Void it instead.").format(item_idx),
			frappe.ValidationError,
		)

	removed_name = row.item_name
	removed_item = row.item
	# Read before the row goes: what it was worth is the one thing the report
	# cannot work out afterwards, because nothing else keeps a trace of a line
	# the kitchen never saw (`D-253`).
	removed_amount = flt(row.amount)
	order.remove(row)
	totals.calculate(order)
	order.save(ignore_permissions=True)

	activity.log(
		order,
		"item_removed",
		subject=removed_name,
		details={"item": removed_item, "row": cint(item_idx), "amount": removed_amount},
	)

	return {"removed": cint(item_idx)}


def void_item(order, *, item_idx: int, reason: str, override_token: str | None = None) -> dict:
	"""Withdraw a line the kitchen has (FR-2.5, BR-013).

	A reason is required here and nowhere else: the food is being made, or was
	made, and somebody has to be able to answer for it later. Removing a line
	before the ticket printed is ``remove_item`` and asks nothing.
	"""
	assert_mutable(order)
	# BR-044 — the same rule as removing, and for the same reason (D-056).

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


# --------------------------------------------------------------------------- #
# Moving lines between bills — splitting and merging
# --------------------------------------------------------------------------- #

#: What a moved line carries with it. Everything that describes *what was
#: ordered* comes across untouched, including `kot_reference`: the food is
#: already cooking under that ticket, it goes to the table rather than to the
#: bill, and re-firing it would cook it twice.
MOVED_FIELDS = (
	"item",
	"item_name",
	"item_name_en",
	"rate",
	"modifiers",
	"notes",
	"production_center",
	"course",
	"status",
	"sent_at",
	"kot_reference",
)


def move_items(source, target, rows: list[dict], *, override_token: str | None = None) -> dict:
	"""Move lines from one bill to another (BR-067).

	**The one operation behind both halves** of what a restaurant calls
	splitting and merging: splitting moves lines onto a *new* order, merging
	moves all of them onto an *existing* one. Written twice, "take this line
	off that bill and put it on this one" is how two bills stop adding up to
	what was eaten.

	**The kitchen is never told.** A line already sent keeps its ticket
	reference and its `sent` status, and no new ticket is printed. Every
	serious POS splits a check without firing the kitchen again, for the plain
	reason that the food is already on the pass.

	``rows`` is ``[{"idx": 3, "qty": 1}]`` and ``qty`` may be less than the
	line: two people sharing a "2 x cola" line is the ordinary case, not the
	exception. Omit it to move the whole line.
	"""
	if source.name == target.name:
		frappe.throw(_("A bill cannot be split into itself."))

	assert_mutable(source)
	assert_mutable(target)
	validate_branch_access(source.branch)
	validate_branch_access(target.branch)

	# Prices follow the order type (`D-020` and the order-type price lists), so
	# a line carried across would keep a rate the receiving bill does not sell
	# at. Refused rather than re-priced: re-pricing changes what a guest was
	# quoted, silently, in the middle of splitting their bill.
	if source.order_type != target.order_type:
		frappe.throw(_("Both bills must be the same order type to move items between them."))

	# An order-level discount has no honest share. `02` §233 settled the same
	# question for returns — "never split by ratio: a bill paid two ways has no
	# right answer for one returned" — and it is the same arithmetic here. The
	# cashier lifts the discount, splits, and applies it again where it belongs.
	for bill in (source, target):
		if flt(bill.discount_amount):
			frappe.throw(
				_("Remove the discount on {0} before moving items — a discount cannot be split.").format(
					bill.name
				)
			)

	authorise("can_split_bill", override_token)

	# **Resolved in full before anything moves.** `Document.remove` renumbers
	# `idx` the moment it takes a line out, so resolving the second spec after
	# carrying the first looks for a row number that no longer means what the
	# caller meant. Holding the row objects also makes the move all-or-nothing:
	# a bill half split because the fourth line was voided is worse than one
	# not split at all.
	picked = [_resolve_line(source, spec) for spec in (rows or [])]
	if not picked:
		frappe.throw(_("Choose at least one item to move."))

	seen = set()
	for row, _qty in picked:
		if row.name in seen:
			frappe.throw(_("Row #{0} is listed twice.").format(row.idx))
		seen.add(row.name)

	moved = [_carry_line(source, target, row, qty) for row, qty in picked]

	# The lines take the receiving bill's status with them.
	#
	# A **draft is an empty bill** — `add_item` promotes one the moment a line is
	# added — so a bill that has just been handed food is not a draft. This was
	# missed at first and the split's second bill sat in the list saying
	# "مسودة" with a dish on it, which is how the distinction came to be
	# questioned at all.
	#
	# And a line already cooking carries `in_kitchen` across, or the bill reads
	# as not yet sent while its food is on the pass.
	if target.status == "draft":
		target.status = "active"
	if any(line["was_sent"] for line in moved) and target.status == "active":
		target.status = "in_kitchen"

	totals.calculate(source)
	source.save(ignore_permissions=True)
	totals.calculate(target)
	target.save(ignore_permissions=True)

	names = ", ".join(line["item_name"] for line in moved)

	# The source side of the story is written by `log_audit` itself, which maps
	# `bill_split` onto the bill's timeline (`utils/audit._ORDER_STORY`). Only
	# the receiving bill needs telling separately — it is not the document the
	# audit entry is about, and a bill that gained three dishes with nothing in
	# its history to say where they came from is the question this log exists
	# to answer.
	log_audit(
		"bill_split",
		branch=source.branch,
		pos_profile=source.pos_profile,
		restaurant_order=source.name,
		reason=names,
		details={"to": target.name, "items": moved},
	)
	activity.log(
		target,
		"items_moved_in",
		subject=names,
		details={"from": source.name, "items": moved},
	)

	return {"source": source.name, "target": target.name, "items": moved}


def _resolve_line(source, spec: dict):
	"""Find the line a spec names and check it may move. Changes nothing."""
	idx = cint(spec.get("idx"))
	row = next((line for line in source.items if line.idx == idx), None)
	if not row:
		frappe.throw(_("Row #{0} is not on this order.").format(idx))

	if row.status == "void":
		frappe.throw(_("Row #{0} is voided.").format(idx))

	qty = flt(spec.get("qty") or row.qty)
	if qty <= 0:
		frappe.throw(_("Quantity must be greater than zero."))
	if qty > flt(row.qty):
		frappe.throw(_("Row #{0} has only {1}.").format(idx, flt(row.qty)))

	return row, qty


def _carry_line(source, target, row, qty: float) -> dict:
	"""Move one resolved line, or part of it, across."""
	carried = target.append("items", {field: row.get(field) for field in MOVED_FIELDS})
	carried.qty = qty
	# Per unit, so moving part of a line keeps the modifier surcharges with it
	# rather than leaving them all behind on the remainder.
	carried.amount = totals.money(flt(row.amount) / flt(row.qty) * qty)

	if qty < flt(row.qty):
		remaining = flt(row.qty) - qty
		row.amount = totals.money(flt(row.amount) / flt(row.qty) * remaining)
		row.qty = remaining
	else:
		source.remove(row)

	return {
		"item": carried.item,
		"item_name": carried.item_name,
		"qty": qty,
		"was_sent": carried.status == "sent",
	}


def preview_split(source, rows: list[dict]) -> dict:
	"""What the two bills would come to, before anything moves (FR-2.12).

	The split screen shows a running total per side, and a total is money — so
	it is computed here rather than on the till (`CLAUDE.md` §5.1). The same
	reason `preview_totals` exists for a discount: a figure a cashier reads to a
	customer must be the figure the invoice will carry.

	Resolves through `_resolve_line`, so the screen refuses exactly what the
	move itself would refuse, at the moment the cashier taps rather than after
	they have arranged the whole bill.
	"""
	picked = [_resolve_line(source, spec) for spec in (rows or [])]
	moving = {id(row): qty for row, qty in picked}

	staying, going = [], []
	for line in source.items:
		if line.status == "void":
			continue

		qty = flt(line.qty)
		moved = flt(moving.get(id(line), 0))
		per_unit = flt(line.amount) / qty if qty else 0.0

		if moved:
			going.append(totals.money(per_unit * moved))
		if qty - moved:
			staying.append(totals.money(per_unit * (qty - moved)))

	pricing = totals.pricing_inputs(source.pos_profile)

	return {
		# The discount is deliberately not carried into either side: a bill
		# carrying one cannot be split at all (`BR-067`), so previewing it as if
		# it could would show a figure the confirm button will refuse.
		"source": totals.compute(staying, None, 0, pricing),
		"target": totals.compute(going, None, 0, pricing),
	}


def split_order(source, rows: list[dict], *, cover_count: int | None = None, **kwargs) -> dict:
	"""Take some lines onto a bill of their own (FR-2.12).

	A second bill on a seated table needs the branch to allow one (`BR-066`),
	which is checked here so the cashier reads why rather than "table 4 is
	occupied" from a rule they were not thinking about.
	"""
	if source.table and not allows_second_bill(source.branch):
		frappe.throw(
			_("This branch keeps one bill per table, so a seated bill cannot be split."),
			frappe.ValidationError,
		)

	target = create_order(
		order_type=source.order_type,
		pos_profile=source.pos_profile,
		table=source.table,
		# The new bill is one party's share; how many people it covers is not
		# knowable from the split and the cashier sets it if it matters.
		cover_count=cover_count or 1,
		waiter=source.waiter,
	)

	return move_items(source, target, rows, **kwargs)


def merge_orders(source, target, **kwargs) -> dict:
	"""Put one bill onto another and close the empty one (FR-2.12).

	The inverse of a split, and the same primitive: everything moves, and the
	bill left with nothing on it is cancelled rather than left open. An empty
	bill on the floor plan is a table somebody has to go and check.
	"""
	rows = [{"idx": row.idx} for row in source.items if row.status != "void"]
	if not rows:
		frappe.throw(_("There is nothing on {0} to merge.").format(source.name))

	result = move_items(source, target, rows, **kwargs)

	# Closed here rather than through , which asks for
	# . There is nothing left to cancel — no lines, and no
	# kitchen tickets to void, because they went with the food — and making a
	# cashier fetch a manager to tidy away an empty document would be a
	# permission guarding nothing.
	source.reload()
	source.status = "cancelled"
	source.cancel_reason = _("Merged into {0}").format(target.name)
	source.cancelled_by = frappe.session.user
	source.closed_at = now_datetime()
	source.save(ignore_permissions=True)

	# **The tables go with the bill** (`D-160`, `D-238`). They used to be
	# released here, which is right when both bills were on one table and wrong
	# the moment they were not: the guests whose bill moved are still sitting
	# where they were, and the floor plan drew their table free while they ate.
	#
	# **Every one of them, not just the first.** This read `source.table` alone,
	# so a party spread over two tables (`BR-063`) left the joined ones pointing
	# at a bill that had just been cancelled: occupied for ever, on a floor plan
	# nobody could clear, until somebody edited the table by hand. The user met
	# it while photographing the guide — table 2 stayed occupied by a bill that
	# no longer existed.
	for table in tables_of(source):
		join_table(target, table)
		release_table(table)

	activity.log(source, "merged", subject=target.name, details={"into": target.name})

	return result | {"merged": source.name}


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

	release_tables_of(order)

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


def allows_second_bill(branch: str | None) -> bool:
	"""Whether this branch lets a table carry more than one open bill (BR-066)."""
	return bool(branch) and bool(frappe.get_cached_value("Branch", branch, "allow_multiple_orders_per_table"))


def tables_of(order) -> list[str]:
	"""Every table this bill occupies — its own first, then the joined ones.

	One party can be spread across two tables (`BR-063`), and a bill knows which
	because **occupancy is read from the bills** and nothing else tracks it. The
	first stays in ``order.table`` so every path that already reads it keeps
	working; the rest ride in ``extra_tables``.
	"""
	joined = [row.table for row in (order.get("extra_tables") or []) if row.table]
	return ([order.table] if order.table else []) + [table for table in joined if table != order.table]


def open_orders_on(table: str) -> list[str]:
	"""The bills still live on a table, oldest first.

	Oldest first so the one a tap opens is the party that sat down first, and so
	releasing the table falls back to a bill that has been waiting rather than
	to whichever was created last.

	**Asked of both places a bill can hold a table** (`D-160`). A bill joined to
	this table from another one is as live on it as a bill opened here, and it
	is this answer that keeps the table drawn occupied: `release_table` reads it,
	and so does everything that reaches a table through `release_table`.
	"""
	# Gathered, then ordered in one query: two sorted lists stitched together are
	# not one sorted list, and `release_table` hands `remaining[0]` to the floor
	# plan as "whoever is still sitting here".
	return frappe.get_all(
		"Restaurant Order",
		filters={"status": ("not in", FINAL_STATES)},
		or_filters={"table": table, "name": ("in", _bills_joined_to(table) or [""])},
		order_by="creation asc",
		pluck="name",
	)


def join_table(order, table: str) -> bool:
	"""Add a table to this bill, if it is not already on it (`BR-063`).

	Saved here rather than left to the caller: the row is what keeps the table
	drawn occupied, and a caller that forgot to save would free a table with
	people at it — the defect this whole seam exists to close.
	"""
	if not table or table in tables_of(order):
		return False

	order.append("extra_tables", {"table": table})
	order.save(ignore_permissions=True)
	return True


def _bills_joined_to(table: str) -> list[str]:
	"""Bills carrying this table in `extra_tables`, whatever their state."""
	return frappe.get_all(
		"Restaurant Order Table",
		filters={"table": table, "parenttype": "Restaurant Order"},
		pluck="parent",
	)


def release_tables_of(order, *, to: str = "available") -> None:
	"""Let go of **every** table this bill was holding (`BR-063`).

	The one place a closing bill hands its seats back. A party across two tables
	is one bill, so paying it or cancelling it frees both — *"the merge is
	reversed when the order closes"*, and this is the reversing.

	Written once and called from the two paths that end a bill, for the reason
	`release_table` itself exists: a condition remembered in two places is a
	condition one of them gets wrong (`D-058`).
	"""
	for table in tables_of(order):
		release_table(table, to=to)


def release_table(table: str, *, to: str = "available") -> None:
	"""Let go of a table when the bill leaving it was the last one (BR-066).

	**Six paths release a table** — paid, cancelled, transferred away, order
	type changed — and every one of them used to say "available, no order".
	With more than one bill allowed that is wrong five times out of six: the
	table is still occupied by whoever is left, and freeing it puts an empty
	seat on the floor plan while people are still eating at it.

	So the question is asked once, here, in the function they all already pass
	through. A condition remembered in six places is a condition five of them
	get right (`D-058`).
	"""
	remaining = open_orders_on(table)
	if remaining:
		set_table_status(table, "occupied", remaining[0])
		return

	set_table_status(table, to, None)


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


# --------------------------------------------------------------------------- #
# Changing the type
# --------------------------------------------------------------------------- #


def assert_convertible(current, target) -> None:
	"""D-038 — an order changes type only when the parties to the sale do not.

	Dine in, takeaway and the restaurant's own delivery all bill the customer
	standing there; only the way the food is served differs, and a customer
	changes their mind about that at the counter every day.

	An app or a corporate order is owed by somebody else. Converting it would
	move the debt onto a party that ordered nothing, and it would strand the
	platform's own order number — the evidence for the monthly statement — on a
	sale that no longer refers to it. That is not an edit; it is a different
	order.
	"""
	for config in (current, target):
		if config.counterparty != "walk_in":
			frappe.throw(
				_("{0} is billed to an account and cannot be converted.").format(config.title),
				frappe.ValidationError,
			)


def preview_order_type_change(order, *, order_type: str) -> dict:
	"""What the bill would become, without changing anything (D-038).

	A total already read out to a customer does not change silently, so the
	cashier sees both figures before confirming. This runs the real repricing on
	a copy the caller never saves.
	"""
	target = _load_order_type(order_type)
	current = frappe.get_cached_doc("Restaurant Order Type", order.order_type)
	assert_convertible(current, target)

	before = flt(order.total_amount)

	# A fresh copy: mutating the caller's document here would leave a half-changed
	# order behind if the cashier says no.
	draft = frappe.get_doc("Restaurant Order", order.name)
	draft.order_type = order_type
	changed = _reprice_lines(draft)
	totals.calculate(draft)

	return {
		"order_type": order_type,
		"price_list": price_list_for(order_type, order.pos_profile),
		"total_before": before,
		"total_after": flt(draft.total_amount),
		"changed_lines": changed,
		"requires_table": bool(target.requires_table),
		"requires_cover_count": bool(target.requires_cover_count),
	}


def change_order_type(
	order,
	*,
	order_type: str,
	table: str | None = None,
	cover_count: int | None = None,
	order_type_data: dict | None = None,
	override_token: str | None = None,
) -> dict:
	"""Turn an open order into another type, re-pricing it (D-038, FR-2.1).

	Allowed after the kitchen has the order: the customer is entitled to change
	their mind, and a restaurant does it anyway. Dine in becoming takeaway
	changes the packing, so the stations that already hold a ticket are told.
	"""
	assert_mutable(order)
	# BR-044 — this re-prices every line, so it moves money like any other cart
	# operation and obeys the same rule (D-056).

	if order.order_type == order_type:
		return {"order_type": order_type, "changed": False}

	target = _load_order_type(order_type)
	current = frappe.get_cached_doc("Restaurant Order Type", order.order_type)
	assert_convertible(current, target)

	approved_by = authorise("can_change_order_type", override_token)

	profile = _load_profile(order.pos_profile)
	validate_branch_access(order.branch)

	seat = table or order.table
	section = section_of_table(seat if target.requires_table else None, profile)
	_assert_order_type_allowed(target, profile, section)

	before = {
		"order_type": order.order_type,
		"price_list": price_list_for(order.order_type, order.pos_profile),
		"total_amount": flt(order.total_amount),
		"table": order.table,
	}

	released = _move_table(order, target, table)
	order.order_type = order_type
	order.section = section

	_apply_cover_count(order, target, cover_count if cover_count is not None else order.cover_count)
	order.order_type_data = _validated_order_type_data(target, order_type_data, moment="on_open")

	changed = _reprice_lines(order)
	_reroute_pending_lines(order)
	totals.calculate(order)

	# The controller refuses a type change it did not come through, so that a
	# stray write cannot leave an order priced from a list it no longer sells
	# from. This is that one path.
	order.flags.rpos_order_type_change = True
	order.save(ignore_permissions=True)

	if released:
		release_table(released)
	if order.table and order.table != before["table"]:
		set_table_status(order.table, "occupied", order.name)

	# Unlike a quantity change, this one decides what the customer pays and how
	# the food leaves the kitchen. It is audited (08 §5).
	log_audit(
		"order_type_changed",
		branch=order.branch,
		pos_profile=order.pos_profile,
		restaurant_order=order.name,
		approved_by=approved_by,
		details={
			"from": before,
			"to": {
				"order_type": order_type,
				"price_list": price_list_for(order_type, order.pos_profile),
				"total_amount": flt(order.total_amount),
				"table": order.table,
			},
			"repriced_lines": changed,
		},
	)

	# A station holding a ticket for a dine-in plate has to hear that it is now
	# going into a bag.
	was_title = frappe.db.get_value("Restaurant Order Type", before["order_type"], "title_ar")
	tickets = kitchen.restamp_order(order, was_title) if _has_sent_lines(order) else []

	return {
		"order_type": order_type,
		"changed": True,
		"total_amount": flt(order.total_amount),
		"repriced_lines": changed,
		"kots": tickets,
	}


def _reroute_pending_lines(order) -> None:
	"""Send the not-yet-printed lines to the stations the new type routes to.

	A routing rule may name an order type (``POS Printer Routing Rule``), so a
	delivery order's fryer work can go to a different station than the dining
	room's. Lines the kitchen already holds keep their station: they are being
	cooked there, and re-pointing the row would only make the audit trail lie.
	"""
	for row in order.items or []:
		if row.status != "pending":
			continue

		route = routing.resolve_route(
			row.item,
			branch=order.branch,
			order_type=order.order_type,
			pos_profile=order.pos_profile,
		)
		row.production_center = route.production_center


def _has_sent_lines(order) -> bool:
	return any(row.status == "sent" for row in order.items or [])


def _move_table(order, target, table: str | None) -> str | None:
	"""Seat or unseat the order for its new type.

	Returns the table to free, if the order is leaving one. Freeing it is left
	to the caller so that nothing is released before the save succeeds.
	"""
	if not target.requires_table:
		leaving = order.table
		order.table = None
		return leaving

	seat = table or order.table
	if not seat:
		frappe.throw(_("Order type {0} requires a table.").format(target.title))

	if seat == order.table:
		return None

	leaving = order.table
	_apply_table(order, target, seat, _load_profile(order.pos_profile))
	return leaving


def _reprice_lines(order) -> list[dict]:
	"""Put every unvoided line on the new type's price list (FR-1.6, D-036).

	A delivery platform's menu is priced above the dining room's, so the list
	the order sells from is part of what the type *means* — leaving the old
	rates behind would sell at the wrong price and hide it in the total.

	Modifier effects are **not** re-read. An option's price effect is a fixed
	amount on the option itself, not a price-list row, so the stored per-unit
	delta is carried across exactly as ``set_item_qty`` carries it.
	"""
	changed: list[dict] = []

	for row in order.items or []:
		# An open price was said at the counter, not read from a list (`D-378`):
		# a new type has no other price for it to move to.
		if row.status == "void" or is_open_price(row.item):
			continue

		qty = flt(row.qty)
		delta_per_unit = (flt(row.amount) / qty) - flt(row.rate) if qty else 0.0

		listed = _listed_rate(order, row.item)
		if listed == flt(row.rate):
			continue

		changed.append({"item": row.item, "item_name": row.item_name, "was": flt(row.rate), "now": listed})
		row.rate = listed
		row.amount = totals.line_amount(listed, qty, delta_per_unit)

	return changed


def _listed_rate(order, item: str) -> float:
	"""The item's price on the order's current price list.

	A price missing from the target list is refused rather than treated as
	zero: converting an order must never quietly make an item free.
	"""
	price_list = price_list_for(order.order_type, order.pos_profile)
	if not price_list:
		frappe.throw(_("POS Profile {0} has no selling price list.").format(order.pos_profile))

	listed = _price_on(item, price_list)
	if listed is None:
		frappe.throw(_("No price is configured for {0} in price list {1}.").format(item, price_list))

	return totals.money(flt(listed))


def _price_on(item: str, price_list: str) -> float | None:
	"""An item's price on a list, or None when the list has none.

	`D-285` — a combo priced by its items starts from its fixed items' prices.
	"""
	if combos.is_combo(item):
		return combos.base_price(item, price_list)
	return frappe.db.get_value(
		"Item Price",
		{"item_code": item, "price_list": price_list, "selling": 1},
		"price_list_rate",
	)


# --------------------------------------------------------------------------- #
# Seating
# --------------------------------------------------------------------------- #


def seat_order(
	order,
	*,
	table: str,
	cover_count: int | None = None,
	override_token: str | None = None,
) -> dict:
	"""Put an open order on a table, or move it to another one (BR-061).

	A cashier rings up a few items and *then* decides where the customer sits —
	which the app could not express at all: a table was attached when the order
	was created and never afterwards. Tapping a table with a bill in hand had to
	either abandon the bill or open a second one.

	**Moving is a different act from seating.** An order with no table is simply
	being placed; one already on a table is being *moved*, which is what
	``can_transfer_table`` has always been for, and which is audited — two bills
	swapping tables is how a customer is handed somebody else's food.
	"""
	assert_mutable(order)

	if order.table == table:
		return {"table": table, "changed": False}

	profile = _load_profile(order.pos_profile)
	validate_branch_access(order.branch)

	leaving = order.table
	approved_by = authorise("can_transfer_table", override_token) if leaving else None

	state = assert_table_free(table, order.branch)

	config = frappe.get_cached_doc("Restaurant Order Type", order.order_type)
	wanted = cover_count if cover_count is not None else (order.cover_count or state.capacity)
	_apply_cover_count(order, config, wanted)

	order.table = table
	# The hall follows the table, the same as it does at creation (D-040).
	order.section = state.section or profile.restaurant_section
	order.save(ignore_permissions=True)

	# Released only after the save: a table freed for an order that then failed
	# to save is a table the floor plan says is empty and the kitchen does not.
	if leaving:
		release_table(leaving)
	set_table_status(table, "occupied", order.name)

	if leaving:
		log_audit(
			"table_changed",
			branch=order.branch,
			pos_profile=order.pos_profile,
			restaurant_order=order.name,
			approved_by=approved_by,
			details={"from": leaving, "to": table},
		)

	return {"table": table, "changed": True, "moved_from": leaving}


def merge_tables(order, *, tables: list[str], override_token: str | None = None) -> dict:
	"""Seat one party across more tables than the bill started on (`BR-063`).

	A group of ten takes tables 5 and 6, and the till has to say so: not two
	bills to reconcile at the end, and not one table drawn free while half of
	them eat at it. So the bill grows a second seat, and a third, and lets go of
	all of them together when it is paid (`FR-5.4`).

	**Square merges tables and leaves the bills alone; Toast merges the checks.**
	They are two operations, and the app has both: this one, and `merge_orders`
	(`BR-067`) which the join screen already offers. What they share is the seam
	underneath — a bill that can hold more than one table — and merging the
	*bills* now carries the table across rather than releasing it, which is what
	stopped the floor plan lying (`D-160`).

	**A table with a bill on it is refused here**, and the refusal says what to
	do instead: joining it would silently strand that bill on a table nobody is
	drawing any more, and the honest answer — put the two bills together — is a
	different act with a different permission and its own audit line.
	"""
	assert_mutable(order)
	validate_branch_access(order.branch)

	if not order.table:
		frappe.throw(_("Seat this order at a table before joining others to it."))

	approved_by = authorise("can_merge_tables", override_token)

	joined = []
	for table in dict.fromkeys(tables or []):
		if table in tables_of(order):
			continue

		# **Asked before `assert_table_free`, and of the bills rather than the
		# status.** That guard lets a second bill onto an occupied table where
		# the branch allows one (`BR-066`), which is right for seating and wrong
		# here — and where the branch does not, it refuses with "table 6 is
		# occupied", which is true and tells the cashier nothing about the thing
		# they can actually do.
		if open_orders_on(table):
			frappe.throw(
				_("Table {0} already has a bill on it. Merge the bills instead.").format(table),
				frappe.ValidationError,
			)

		assert_table_free(table, order.branch)
		join_table(order, table)
		set_table_status(table, "occupied", order.name)
		joined.append(table)

	if not joined:
		frappe.throw(_("Choose at least one free table to join."))

	log_audit(
		"tables_merged",
		branch=order.branch,
		pos_profile=order.pos_profile,
		restaurant_order=order.name,
		approved_by=approved_by,
		details={"onto": order.table, "joined": joined},
	)
	activity.log(order, "tables_merged", subject=", ".join(joined), details={"joined": joined})

	return {"table": order.table, "tables": tables_of(order), "joined": joined}


def set_call_name(order, *, call_name: str | None) -> dict:
	"""Name the order for calling out (FR-2.11).

	Not a Customer. "Hamza" waiting on a takeaway is somebody to shout at, not
	somebody to file — and making the cashier create a customer record to write
	a name down is how a database fills with people nobody meant to keep.
	"""
	assert_mutable(order)

	cleaned = (call_name or "").strip() or None
	if cleaned == order.call_name:
		return {"call_name": order.call_name, "changed": False}

	order.call_name = cleaned
	order.save(ignore_permissions=True)

	# The counter shouts the name, so a ticket already at a station needs it.
	tickets = kitchen.restamp_order(order) if _has_sent_lines(order) else []
	return {"call_name": order.call_name, "changed": True, "kots": tickets}


def set_order_notes(order, *, notes: str | None) -> dict:
	"""Set the note that goes to every station (FR-2.9).

	Editable after the fact on purpose: a customer says "make it quick" once the
	order is already in, and a field that could only be filled at creation would
	be a field nobody uses.

	Stations that already hold a ticket are re-stamped, or the note would reach
	only the dishes rung up after it — which is the failure this note exists to
	prevent.
	"""
	assert_mutable(order)

	cleaned = (notes or "").strip() or None
	if cleaned == order.notes:
		return {"notes": order.notes, "changed": False}

	order.notes = cleaned
	order.save(ignore_permissions=True)

	tickets = kitchen.restamp_order(order) if _has_sent_lines(order) else []
	return {"notes": order.notes, "changed": True, "kots": tickets}


def set_item_notes(order, *, item_idx: int, notes: str | None) -> dict:
	"""Change one line's note — for any item, at any time (FR-2.9).

	**Any item.** A note used to be reachable only through the modifier popup,
	which opens only for items that have modifier groups: a plain dish could
	never be given one. Every line takes a note.

	**At any time.** Unlike a quantity (``set_item_qty``), a note may be changed
	after the kitchen has the line — "actually, no onion" is the commonest thing
	a customer says once the order is in. The station's ticket is corrected so
	it never disagrees with the bill; a note the kitchen was not told is a note
	that did not happen.
	"""
	assert_mutable(order)

	row = next((line for line in order.items if line.idx == cint(item_idx)), None)
	if not row:
		frappe.throw(_("Row #{0} is not on this order.").format(item_idx))

	if row.status == "void":
		frappe.throw(_("Row #{0} is voided.").format(item_idx))

	cleaned = (notes or "").strip() or None
	if cleaned == row.notes:
		return {"item_idx": row.idx, "notes": row.notes, "changed": False}

	row.notes = cleaned
	order.save(ignore_permissions=True)

	told = kitchen.restamp_item(order, row) if row.status == "sent" else []
	return {"item_idx": row.idx, "notes": row.notes, "changed": True, "kots": told}

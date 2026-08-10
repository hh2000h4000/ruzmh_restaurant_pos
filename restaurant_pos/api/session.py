# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Everything a terminal needs to start working.

``load_pos_session`` is the contract between the backend and the Vue app
(``07_API_Design.md`` §2). It is called once at login and its result is what
``09_Offline_Synchronization.md`` §3 caches in IndexedDB, so a terminal that
loses its connection keeps a full menu, layout and configuration.

That makes two things matter more here than anywhere else:

* **No N+1.** The whole payload is assembled in a fixed number of queries. A
  per-item price lookup over a 400-line menu is 400 round trips on the slowest
  screen in the product (``04`` §8: first load under 3 seconds).
* **One rule, one place.** Which order types appear is decided by the same
  predicate that decides whether an order may be created. A button the cashier
  taps and is then refused is worse than no button.

Refs: 07 §2, 09 §3, FR-1.3, FR-3.5, FR-15.4, 04 §8
"""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from restaurant_pos.utils.order import is_order_type_allowed
from restaurant_pos.utils.permissions import get_pos_permission_set, validate_branch_access

#: The Phase 2 design tokens (FR-15.4). Hardcoded defaults for now; Phase 4
#: replaces them with the resolved ``RPOS Theme`` record (FR-15.2, D-014).
#: The Vue app reads its colours from here from day one, so no component ever
#: needs a hardcoded brand colour.
DEFAULT_THEME = {
	"primary": "#1D4ED8",
	"primary_contrast": "#FFFFFF",
	"secondary": "#F59E0B",
	"secondary_contrast": "#FFFFFF",
	"surface": "#FFFFFF",
	"background": "#F3F4F6",
	"text": "#111827",
	"brand_logo": None,
}


@frappe.whitelist()
def ping() -> dict:
	"""Connectivity probe for the sync engine (``09`` §2).

	Deliberately trivial: it must answer while the site is under load, because
	a slow answer is read as an outage and puts the terminal into offline mode.
	"""
	return {"status": "ok", "timestamp": now_datetime()}


@frappe.whitelist()
def load_pos_session(pos_profile: str) -> dict:
	"""The full terminal payload (07 §2)."""
	profile = _profile(pos_profile)
	validate_branch_access(profile.branch)

	section = (
		frappe.db.get_value(
			"Restaurant Section",
			profile.restaurant_section,
			["name", "title", "title_ar", "branch", "section_type", "has_tables"],
			as_dict=True,
		)
		if profile.restaurant_section
		else None
	)

	items, item_groups = _catalog(profile)

	return {
		"pos_profile": profile,
		"restaurant_section": section,
		"branch": _branch(profile.branch),
		"screen_layout": _screen_layout(profile.screen_layout),
		"order_types": _order_types(profile),
		"payment_methods": _payment_methods(pos_profile),
		"active_shift": _active_shift(profile),
		"items": items,
		"item_groups": item_groups,
		"promotions": _promotions(profile.branch),
		"permissions": get_pos_permission_set(),
		"theme": DEFAULT_THEME,
		"server_time": now_datetime(),
	}


# --------------------------------------------------------------------------- #
# Pieces
# --------------------------------------------------------------------------- #


def _profile(pos_profile: str) -> frappe._dict:
	profile = frappe.db.get_value(
		"POS Profile",
		pos_profile,
		[
			"name",
			"company",
			"currency",
			"warehouse",
			"selling_price_list",
			"taxes_and_charges",
			"customer",
			"restaurant_section",
			"screen_layout",
			"default_printer",
			"restaurant_shift",
		],
		as_dict=True,
	)
	if not profile:
		frappe.throw(_("POS Profile {0} does not exist.").format(pos_profile))

	profile.branch = (
		frappe.db.get_value("Restaurant Section", profile.restaurant_section, "branch")
		if profile.restaurant_section
		else None
	)
	return profile


def _branch(branch: str | None) -> dict | None:
	if not branch:
		return None

	return frappe.db.get_value(
		"Branch", branch, ["name", "branch", "vat_number", "settlement_required"], as_dict=True
	)


def _screen_layout(layout: str | None) -> dict | None:
	"""FR-3.5 — the layout assigned to this terminal, with its buttons."""
	if not layout:
		return None

	doc = frappe.db.get_value(
		"POS Screen Layout",
		layout,
		["name", "title", "grid_columns", "grid_rows", "background_color", "is_active"],
		as_dict=True,
	)
	if not doc or not doc.is_active:
		return None

	doc.buttons = frappe.get_all(
		"POS Screen Layout Button",
		filters={"parent": layout, "parenttype": "POS Screen Layout"},
		fields=[
			"idx",
			"button_type",
			"item",
			"item_group",
			"goto_screen",
			"action_type",
			"col_start",
			"col_span",
			"row_start",
			"row_span",
			"display_text",
			"display_text_ar",
			"bg_color",
			"text_color",
			"font_size",
			"image",
		],
		order_by="idx",
	)
	return doc


def _order_types(profile) -> list[dict]:
	"""FR-1.3 — filtered by role, terminal and branch, in display order."""
	permitted = {
		row.order_type
		for row in frappe.get_all(
			"POS Profile Order Type",
			filters={"parent": profile.name, "parenttype": "POS Profile"},
			fields=["order_type"],
		)
	}

	rows = []
	for name in frappe.get_all(
		"Restaurant Order Type", filters={"is_active": 1}, order_by="sort_order asc", pluck="name"
	):
		if permitted and name not in permitted:
			continue

		config = frappe.get_cached_doc("Restaurant Order Type", name)
		if not is_order_type_allowed(config, profile):
			continue

		rows.append(
			{
				"name": config.name,
				"title": config.title,
				"title_ar": config.title_ar,
				"icon": config.icon,
				"color": config.color,
				"requires_table": config.requires_table,
				"requires_cover_count": config.requires_cover_count,
				"customer_mode": config.customer_mode,
				"send_to_kitchen_on": config.send_to_kitchen_on,
				"sort_order": config.sort_order,
				"hidden_item_groups": [row.item_group for row in config.hidden_item_groups],
				"additional_fields": [
					{
						"label": row.field_label,
						"label_ar": row.field_label_ar,
						"type": row.field_type,
						"options": [
							line.strip() for line in (row.field_options or "").splitlines() if line.strip()
						],
						"is_required": row.is_required,
						"show_at": row.show_at,
						"placeholder": row.placeholder,
					}
					for row in config.additional_fields
				],
				"payment_methods": [
					{
						"method": row.payment_method,
						"is_forced": row.is_forced,
						"is_default": row.is_default,
					}
					for row in config.allowed_payment_methods
				],
			}
		)

	return rows


def _payment_methods(pos_profile: str) -> list[dict]:
	return frappe.get_all(
		"POS Payment Method",
		filters={"parent": pos_profile, "parenttype": "POS Profile"},
		fields=["mode_of_payment", "default", "allow_in_returns"],
		order_by="idx",
	)


def _active_shift(profile) -> dict | None:
	"""BR-040 — the shift this terminal is working under, if one is open."""
	if not profile.restaurant_shift:
		return None

	shift = frappe.db.get_value(
		"Restaurant Shift",
		profile.restaurant_shift,
		["name", "title", "shift_date", "shift_type", "status", "opened_by", "opened_at"],
		as_dict=True,
	)
	return shift if shift and shift.status == "open" else None


def _catalog(profile) -> tuple[list[dict], list[dict]]:
	"""The menu, assembled in a fixed number of queries regardless of its size.

	Prices, modifier groups and item groups are each fetched once and joined in
	memory. Looking any of them up per item is the N+1 pattern that would make
	login crawl on a real menu (``04`` §8).
	"""
	items = frappe.get_all(
		"Item",
		filters={"disabled": 0, "is_sales_item": 1},
		fields=[
			"name as item_code",
			"item_name",
			"pos_display_name_ar",
			"item_group",
			"stock_uom",
			"image",
			"default_production_center",
		],
		order_by="item_name asc",
	)
	if not items:
		return [], _item_groups()

	codes = [row.item_code for row in items]

	prices = {}
	if profile.selling_price_list:
		for row in frappe.get_all(
			"Item Price",
			filters={
				"price_list": profile.selling_price_list,
				"selling": 1,
				"item_code": ("in", codes),
			},
			fields=["item_code", "price_list_rate"],
		):
			prices[row.item_code] = flt(row.price_list_rate)

	modifiers: dict[str, list[str]] = {}
	for row in frappe.get_all(
		"Modifier Group Assignment",
		filters={"parenttype": "Item", "parent": ("in", codes)},
		fields=["parent", "modifier_group"],
		order_by="idx",
	):
		modifiers.setdefault(row.parent, []).append(row.modifier_group)

	for row in items:
		# None, not 0: an item with no price cannot be sold, and the UI must be
		# able to tell that apart from a deliberately free item (D-020).
		row.rate = prices.get(row.item_code)
		row.modifier_groups = modifiers.get(row.item_code, [])
		row.display_name = row.pos_display_name_ar or row.item_name

	return items, _item_groups()


def _item_groups() -> list[dict]:
	return frappe.get_all(
		"Item Group",
		filters={"is_group": 0},
		fields=["name", "item_group_name", "parent_item_group", "default_production_center"],
		order_by="name asc",
	)


def _promotions(branch: str | None) -> list[dict]:
	"""Active promotions, cached for the client (``09`` §4).

	Returned unevaluated: whether one applies to a given order is the promotion
	engine's job in Phase 4. This is the data it will need.
	"""
	today = now_datetime().date()
	return frappe.get_all(
		"Restaurant Promotion",
		filters={"is_active": 1},
		# A promotion with no end date runs until someone turns it off.
		or_filters=[["valid_to", "is", "not set"], ["valid_to", ">=", today]],
		fields=[
			"name",
			"title",
			"title_ar",
			"promotion_type",
			"discount_value",
			"free_item",
			"apply_to",
			"item_scope",
			"is_auto_apply",
			"is_exclusive",
			"valid_from",
			"valid_to",
			"time_from",
			"time_to",
		],
	)


@frappe.whitelist()
def get_modifier_groups(groups: list | None = None) -> list[dict]:
	"""Modifier groups with their options, for the item popup (FR-4.4)."""
	if isinstance(groups, str):
		groups = frappe.parse_json(groups)

	filters = {"name": ("in", groups)} if groups else {}
	rows = frappe.get_all(
		"POS Modifier Group",
		filters=filters,
		fields=[
			"name",
			"title",
			"title_ar",
			"selection_type",
			"is_required",
			"min_selections",
			"max_selections",
		],
	)
	if not rows:
		return []

	options: dict[str, list[dict]] = {}
	for option in frappe.get_all(
		"POS Modifier Option",
		filters={
			"parenttype": "POS Modifier Group",
			"parent": ("in", [r.name for r in rows]),
			"is_active": 1,
		},
		fields=["parent", "title", "title_ar", "price_effect", "price_amount", "is_default"],
		order_by="idx",
	):
		options.setdefault(option.parent, []).append(option)

	for row in rows:
		row.options = options.get(row.name, [])

	return rows

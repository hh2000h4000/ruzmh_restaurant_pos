# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Default data shipped with the app (Phase 1 task 3).

Created once, at install time. Never on migrate.

``docs/08_Security.md`` §3 states that every permission-set default is
configurable, and ``docs/02_Business_Requirements.md`` §3 says the same about
order types. Frappe's ``fixtures`` hook re-imports its records on every
``bench migrate``, which would silently overwrite whatever the restaurant had
configured. So each record here is created only when it is missing, and is
never touched again.

Refs: 10_Implementation_Plan.md Phase 1 task 3, BR-001, BR-031, 08 §3
"""

import frappe
from frappe.utils import flt

# --------------------------------------------------------------------------- #
# POS Permission Sets — 08_Security.md §3
# --------------------------------------------------------------------------- #
# manager_pin is deliberately left unset. A shipped default PIN would be a
# known credential on every installation.

_CASHIER = {
	"max_item_discount_pct": 0,
	"max_order_discount_pct": 0,
	"can_manual_promotion": 0,
	"can_void_item": 1,
	"can_void_order": 0,
	"can_cancel_order": 0,
	"can_transfer_table": 1,
	"can_merge_tables": 0,
	"can_reopen_closed_order": 0,
	"can_change_item_price": 0,
	"can_create_return": 0,
	"can_reprint_receipt": 1,
	"can_override_payment_method": 0,
	"can_open_shift": 1,
	"can_close_shift": 1,
	"can_close_others_shift": 0,
	"can_view_all_orders": 0,
	"can_access_reports": 0,
}

_SENIOR_CASHIER = _CASHIER | {
	"max_item_discount_pct": 10,
	"max_order_discount_pct": 10,
	"can_manual_promotion": 1,
	"can_create_return": 1,
}

_POS_MANAGER = _SENIOR_CASHIER | {
	"max_item_discount_pct": 50,
	"max_order_discount_pct": 50,
	"can_void_order": 1,
	"can_cancel_order": 1,
	"can_merge_tables": 1,
	"can_reopen_closed_order": 1,
	"can_change_item_price": 1,
	"can_override_payment_method": 1,
	"can_close_others_shift": 1,
	"can_view_all_orders": 1,
	"can_access_reports": 1,
}

# 08 §2 places Restaurant Manager and Restaurant Admin above POS Manager but
# gives no discount ceilings; both get full authority (DECISIONS.md D-013).
_RESTAURANT_MANAGER = _POS_MANAGER | {
	"max_item_discount_pct": 100,
	"max_order_discount_pct": 100,
}

PERMISSION_SETS = {
	"POS Cashier": _CASHIER,
	"POS Senior Cashier": _SENIOR_CASHIER,
	"POS Manager": _POS_MANAGER,
	"Restaurant Manager": _RESTAURANT_MANAGER,
	"Restaurant Admin": _RESTAURANT_MANAGER,
}


# --------------------------------------------------------------------------- #
# Order Types — 02_Business_Requirements.md §3
# --------------------------------------------------------------------------- #
# Visibility tables are left empty on purpose: empty means "every branch,
# section, POS profile and role", so the defaults work before any branch
# exists.

ORDER_TYPES = [
	{
		"title": "Dine In",
		"title_ar": "محلي",
		"icon": "🏠",
		"color": "#1D4ED8",
		"requires_table": 1,
		"requires_cover_count": 1,
		"customer_mode": "optional",
		"send_to_kitchen_on": "manual",
		"sort_order": 1,
	},
	{
		"title": "Takeaway",
		"title_ar": "سفري",
		"icon": "🥡",
		"color": "#F59E0B",
		"requires_table": 0,
		"requires_cover_count": 0,
		"customer_mode": "optional",
		"send_to_kitchen_on": "payment",
		"sort_order": 2,
	},
	{
		"title": "Delivery",
		"title_ar": "توصيل خاص",
		"icon": "🛵",
		"color": "#22C55E",
		"requires_table": 0,
		"requires_cover_count": 0,
		"customer_mode": "required",
		"send_to_kitchen_on": "save",
		"sort_order": 3,
	},
]

# --------------------------------------------------------------------------- #
# Delivery-app order types — 02_Business_Requirements.md §3
# --------------------------------------------------------------------------- #
# Shipped **inactive**. Everything the platform dictates is preset: the forced
# payment method (BR-002), the app's order number as a required field (BR-004),
# and `customer_mode = pre_set`. What is missing is the one thing only the
# restaurant knows — which Customer the platform's money is receivable from.
# Creating that Customer here would invent an accounting entity the accountant
# never approved, so the manager links it and activates the type.
#
# `corporate` from §3 is deliberately absent: it is billed on credit, and
# BR-022 forbids anything but payment in full in v1. Shipping a type that
# cannot complete a sale is worse than not shipping it (`DECISIONS.md` D-028).

APP_ORDER_NUMBER_FIELD = {
	"field_label": "App Order No",
	"field_label_ar": "رقم الطلب في التطبيق",
	"field_type": "text",
	"is_required": 1,
	"show_at": "on_open",
	"placeholder": "HS-29541",
}

DELIVERY_APPS = [
	{"title": "HungerStation", "title_ar": "هنقرستيشن", "icon": "🛵", "color": "#F59E0B", "sort_order": 4},
	{"title": "Jahez", "title_ar": "جاهز", "icon": "📱", "color": "#EF4444", "sort_order": 5},
	{"title": "Talabat", "title_ar": "طلبات", "icon": "📱", "color": "#22C55E", "sort_order": 6},
]

APP_ORDER_TYPES = [
	{
		"title": app["title"],
		"title_ar": app["title_ar"],
		"icon": app["icon"],
		"color": app["color"],
		"requires_table": 0,
		"requires_cover_count": 0,
		"customer_mode": "pre_set",
		"send_to_kitchen_on": "save",
		"sort_order": app["sort_order"],
		"is_active": 0,
		"allowed_payment_methods": [{"payment_method": app["title"], "is_forced": 1, "is_default": 1}],
		"additional_fields": [dict(APP_ORDER_NUMBER_FIELD)],
	}
	for app in DELIVERY_APPS
]


# --------------------------------------------------------------------------- #
# Sample promotion — inactive, meant to be copied
# --------------------------------------------------------------------------- #

SAMPLE_PROMOTION = {
	"title": "Happy Hour (sample)",
	"title_ar": "ساعة السعادة (نموذج)",
	"promotion_type": "percentage",
	"discount_value": 20,
	"apply_to": "all",
	"item_scope": "all",
	"time_from": "15:00:00",
	"time_to": "17:00:00",
	"sunday": 1,
	"monday": 1,
	"tuesday": 1,
	"wednesday": 1,
	"thursday": 1,
	"is_auto_apply": 0,
	"is_exclusive": 0,
	"is_active": 0,
}


# --------------------------------------------------------------------------- #
# Creation
# --------------------------------------------------------------------------- #


def create_default_data():
	"""Create the shipped defaults. Safe to call twice: existing records are kept."""
	_configure_cash_rounding()
	created = {
		"payment_methods": _create_app_payment_methods(),
		"permission_sets": _create_permission_sets(),
		"order_types": _create_order_types(),
		"promotions": _create_sample_promotion(),
	}
	frappe.db.commit()
	return created


def _configure_cash_rounding():
	"""Teach ERPNext the Saudi 0.05 cash rounding step (BR-024).

	``Currency.smallest_currency_fraction_value`` ships as 0 for SAR, which makes
	ERPNext round invoice totals to whole riyals. Setting it here means the order
	screen and the Sales Invoice round identically, and the difference posts to
	the company's Round Off account like any other rounding adjustment.

	Only set when unconfigured — a site that deliberately chose another step
	keeps it (``DECISIONS.md`` D-023).
	"""
	if not frappe.db.exists("Currency", "SAR"):
		return

	if flt(frappe.db.get_value("Currency", "SAR", "smallest_currency_fraction_value")):
		return

	frappe.db.set_value("Currency", "SAR", "smallest_currency_fraction_value", 0.05)


def _create_permission_sets():
	created = []
	for role, values in PERMISSION_SETS.items():
		if frappe.db.exists("POS Permission Set", role) or not frappe.db.exists("Role", role):
			continue

		doc = frappe.get_doc({"doctype": "POS Permission Set", "role": role} | values)
		doc.insert(ignore_permissions=True)
		created.append(doc.name)

	return created


def _create_app_payment_methods():
	"""One Mode of Payment per delivery app (BR-002).

	The platform settles by transfer, so these are bank-type methods rather than
	cash. Keeping them separate is what lets the shift report show what each
	platform owes.
	"""
	created = []
	for app in DELIVERY_APPS:
		if frappe.db.exists("Mode of Payment", app["title"]):
			continue

		doc = frappe.get_doc({"doctype": "Mode of Payment", "mode_of_payment": app["title"], "type": "Bank"})
		doc.insert(ignore_permissions=True)
		created.append(doc.name)

	return created


def _create_order_types():
	created = []
	for values in ORDER_TYPES + APP_ORDER_TYPES:
		if frappe.db.exists("Restaurant Order Type", {"title": values["title"]}):
			continue

		doc = frappe.get_doc({"doctype": "Restaurant Order Type", "is_active": 1} | values)
		doc.insert(ignore_permissions=True)
		created.append(doc.name)

	return created


def _create_sample_promotion():
	if frappe.db.exists("Restaurant Promotion", {"title": SAMPLE_PROMOTION["title"]}):
		return []

	doc = frappe.get_doc({"doctype": "Restaurant Promotion"} | SAMPLE_PROMOTION)
	doc.insert(ignore_permissions=True)
	return [doc.name]

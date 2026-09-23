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

**Adding a right here is only half the change** (`D-167`). This module runs at
install and never again, so a field added later reaches a site installed before
it at `0` — the column was born empty and nothing writes the shipped value. It
needs a patch beside `patches/v1_0/grant_missing_permission_defaults.py`, and
`tests/test_shipped_defaults.py` turns the gate red until there is one.

Refs: 10_Implementation_Plan.md Phase 1 task 3, BR-001, BR-031, 08 §3, D-167
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
	"can_change_order_type": 0,
	"can_transfer_table": 1,
	"can_merge_tables": 0,
	# Guests ask to be billed separately at the till, not in the office.
	# It is audited, and it is reversible until somebody pays.
	"can_split_bill": 1,
	"can_reopen_closed_order": 0,
	"can_change_item_price": 0,
	"can_create_return": 0,
	"can_reprint_receipt": 1,
	"can_override_payment_method": 0,
	"can_open_shift": 1,
	"can_close_shift": 1,
	"can_close_others_shift": 0,
	# `D-156` — closing the day is a cashier's job; closing it **over open
	# bills** is not. The branch setting is the rule (`D-105`) and this is the
	# only way past it, so the till's two honest answers stay the ordinary ones:
	# settle the bills, or cancel them.
	"can_close_day_with_open_orders": 0,
	"can_view_all_orders": 0,
	"can_access_reports": 0,
}

_SENIOR_CASHIER = _CASHIER | {
	"max_item_discount_pct": 10,
	"max_order_discount_pct": 10,
	"can_manual_promotion": 1,
	"can_create_return": 1,
	# Turning a takeaway into a dine-in changes nothing about who pays, and it
	# happens at the counter all day (D-038).
	"can_change_order_type": 1,
}

_POS_MANAGER = _SENIOR_CASHIER | {
	"max_item_discount_pct": 50,
	"max_order_discount_pct": 50,
	"can_void_order": 1,
	"can_cancel_order": 1,
	"can_change_order_type": 1,
	"can_merge_tables": 1,
	"can_reopen_closed_order": 1,
	"can_change_item_price": 1,
	"can_override_payment_method": 1,
	"can_close_others_shift": 1,
	"can_close_day_with_open_orders": 1,
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
#
# ``counterparty`` says who owes the money, and it is what decides whether an
# order may be turned into another type (D-038). The three below are all
# ``walk_in``: the customer is standing there, and only the way the food is
# served differs between them.

ORDER_TYPES = [
	{
		"title": "Dine In",
		"title_ar": "محلي",
		"icon": "home",
		"color": "#1D4ED8",
		"requires_table": 1,
		"requires_cover_count": 1,
		"counterparty": "walk_in",
		"customer_mode": "optional",
		"send_to_kitchen_on": "manual",
		"sort_order": 1,
	},
	{
		"title": "Takeaway",
		"title_ar": "سفري",
		"icon": "bag",
		"color": "#F59E0B",
		"requires_table": 0,
		"requires_cover_count": 0,
		"counterparty": "walk_in",
		"customer_mode": "optional",
		"send_to_kitchen_on": "payment",
		"sort_order": 2,
	},
	{
		"title": "Delivery",
		"title_ar": "توصيل خاص",
		"icon": "truck",
		"color": "#22C55E",
		"requires_table": 0,
		"requires_cover_count": 0,
		"counterparty": "walk_in",
		"customer_mode": "required",
		"send_to_kitchen_on": "save",
		"sort_order": 3,
	},
]

# --------------------------------------------------------------------------- #
# Delivery-app order types — 02_Business_Requirements.md §3
# --------------------------------------------------------------------------- #
# An app order is already paid — to the platform, not to the restaurant. The
# cashier keys it in and closes it on the platform's own payment method, which
# is **credit**: nothing enters the till, the invoice stays outstanding against
# the platform, and the two settle monthly on a statement (D-029).
#
# Shipped **inactive**, because the one thing only the restaurant knows is
# missing: which Customer the platform's money is receivable from. Creating that
# record here would invent an accounting entity the accountant never approved.

APP_ORDER_NUMBER_FIELD = {
	"field_label": "App Order No",
	"field_label_ar": "رقم الطلب في التطبيق",
	"field_type": "text",
	"is_required": 1,
	"show_at": "on_open",
	"placeholder": "HS-29541",
}

DELIVERY_APPS = [
	{
		"title": "HungerStation",
		"title_ar": "هنقرستيشن",
		"icon": "mobile",
		"color": "#F59E0B",
		"sort_order": 4,
	},
	{"title": "Jahez", "title_ar": "جاهز", "icon": "mobile", "color": "#EF4444", "sort_order": 5},
	{"title": "Talabat", "title_ar": "طلبات", "icon": "mobile", "color": "#22C55E", "sort_order": 6},
]

#: A general credit method for corporate accounts (02 §3, "Invoice/Credit").
CREDIT_METHOD = "Credit"

APP_ORDER_TYPES = [
	{
		"title": app["title"],
		"title_ar": app["title_ar"],
		"icon": app["icon"],
		"color": app["color"],
		"requires_table": 0,
		"requires_cover_count": 0,
		# The platform owes the money and holds its own order number: this can
		# never become a walk-in sale, nor another app's (D-038).
		"counterparty": "account",
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
# Quick notes — FR-2.9
# --------------------------------------------------------------------------- #
# The notes a kitchen hears every day, so the feature is useful before anybody
# configures anything. A restaurant edits the list; nothing here is special.
#
# `scope` decides where a note may be used: an **item** note travels with its
# line to the one station that cooks it, an **order** note is printed on the
# header of every station's ticket.

QUICK_NOTES = [
	{"title": "No onion", "title_ar": "بدون بصل", "scope": "item", "sort_order": 1},
	{"title": "No pickles", "title_ar": "بدون مخلل", "scope": "item", "sort_order": 2},
	{"title": "No sauce", "title_ar": "بدون صوص", "scope": "item", "sort_order": 3},
	{"title": "Extra spicy", "title_ar": "حار زيادة", "scope": "item", "sort_order": 4},
	{"title": "Not spicy", "title_ar": "بدون حار", "scope": "item", "sort_order": 5},
	{"title": "Well done", "title_ar": "استواء تام", "scope": "item", "sort_order": 6},
	{"title": "On the side", "title_ar": "على جنب", "scope": "item", "sort_order": 7},
	{"title": "Rush this order", "title_ar": "الطلب مستعجل", "scope": "order", "sort_order": 20},
	{"title": "Serve together", "title_ar": "يُقدّم كله مع بعض", "scope": "order", "sort_order": 21},
	{
		"title": "Allergy — ask the cashier",
		"title_ar": "حساسية — راجع الكاشير",
		"scope": "order",
		"sort_order": 22,
	},
	{"title": "Cutlery included", "title_ar": "مع أدوات المائدة", "scope": "both", "sort_order": 30},
	{"title": "No cutlery", "title_ar": "بدون أدوات مائدة", "scope": "both", "sort_order": 31},
	# **Why, tapped rather than typed** (`D-239`). The answers to "why was this
	# voided" and "why was this bill cancelled" are the same handful every day,
	# and they are typed one-handed with a customer waiting. A restaurant edits
	# this list like any other.
	{
		"title": "Customer changed their mind",
		"title_ar": "الزبون غيّر رأيه",
		"scope": "void_reason",
		"sort_order": 40,
	},
	{"title": "Rung up by mistake", "title_ar": "انضاف بالغلط", "scope": "void_reason", "sort_order": 41},
	{"title": "Out of stock", "title_ar": "الصنف خلص", "scope": "void_reason", "sort_order": 42},
	{"title": "Wrong item", "title_ar": "صنف خطأ", "scope": "void_reason", "sort_order": 43},
	{
		"title": "Customer left",
		"title_ar": "الزبون انسحب",
		"scope": "cancel_reason",
		"sort_order": 50,
	},
	{
		"title": "Opened by mistake",
		"title_ar": "الفاتورة انفتحت بالغلط",
		"scope": "cancel_reason",
		"sort_order": 51,
	},
	{"title": "Took too long", "title_ar": "التحضير تأخر", "scope": "cancel_reason", "sort_order": 52},
	{
		"title": "Moved to another bill",
		"title_ar": "تحوّل لفاتورة ثانية",
		"scope": "cancel_reason",
		"sort_order": 53,
	},
	# `D-245` — why notes left the drawer or came into it. The four a restaurant
	# actually uses; anything rarer is still typed.
	{
		"title": "Change from the safe",
		"title_ar": "فكّة من الخزنة",
		"scope": "cash_reason",
		"sort_order": 60,
	},
	{
		"title": "Bought supplies",
		"title_ar": "شراء مستلزمات",
		"scope": "cash_reason",
		"sort_order": 61,
	},
	{
		"title": "Cash to the safe",
		"title_ar": "تحويل للخزنة",
		"scope": "cash_reason",
		"sort_order": 62,
	},
	{
		"title": "Delivery driver float",
		"title_ar": "عهدة مندوب التوصيل",
		"scope": "cash_reason",
		"sort_order": 63,
	},
]


#: 02 §3 — billed to the company, settled on a statement like the apps.
CORPORATE_ORDER_TYPE = {
	"title": "Corporate",
	"title_ar": "شركات",
	"icon": "users",
	"color": "#6B7280",
	"requires_table": 0,
	"requires_cover_count": 0,
	"counterparty": "account",
	"customer_mode": "required",
	"send_to_kitchen_on": "manual",
	"sort_order": 7,
	"is_active": 0,
	"allowed_payment_methods": [{"payment_method": CREDIT_METHOD, "is_forced": 1, "is_default": 1}],
}


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
		"payment_methods": _create_credit_payment_methods(),
		"permission_sets": _create_permission_sets(),
		"order_types": _create_order_types(),
		"promotions": _create_sample_promotion(),
		"quick_notes": _create_quick_notes(),
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


def _create_quick_notes():
	"""FR-2.9 — a starter list, skipped once a title exists.

	Matched on the English title, which is the record's name: a restaurant that
	renamed or deleted one keeps its decision.
	"""
	created = []
	for values in QUICK_NOTES:
		if frappe.db.exists("POS Quick Note", values["title"]):
			continue

		frappe.get_doc(dict(doctype="POS Quick Note", is_active=1, **values)).insert(ignore_permissions=True)
		created.append(values["title"])

	return created


def _create_credit_payment_methods():
	"""One credit method per platform, plus a general one for corporate accounts.

	``type = General`` with ``rpos_is_credit = 1``: no till, no bank account,
	nothing to reconcile at close of shift. One method per platform rather than
	a single shared "Credit" is what lets a statement be pulled per platform —
	HungerStation and Jahez owe separately (``DECISIONS.md`` D-029).
	"""
	created = []
	for title in [app["title"] for app in DELIVERY_APPS] + [CREDIT_METHOD]:
		if frappe.db.exists("Mode of Payment", title):
			continue

		doc = frappe.get_doc(
			{
				"doctype": "Mode of Payment",
				"mode_of_payment": title,
				"type": "General",
				"rpos_is_credit": 1,
			}
		)
		doc.insert(ignore_permissions=True)
		created.append(doc.name)

	return created


def _create_order_types():
	created = []
	for values in ORDER_TYPES + APP_ORDER_TYPES + [CORPORATE_ORDER_TYPE]:
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

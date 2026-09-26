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
import frappe.sessions
from frappe import _
from frappe.utils import cint, flt, now_datetime

from restaurant_pos.utils import device
from restaurant_pos.utils import theme as theme_service
from restaurant_pos.utils import totals as totals_service
from restaurant_pos.utils.gift_card import is_gift_card_method
from restaurant_pos.utils.order import is_order_type_allowed
from restaurant_pos.utils.permissions import (
	assert_pos_user,
	get_pos_permission_set,
	validate_branch_access,
)

#: How long each banner holds the customer's screen when nobody has said
#: otherwise (`D-203`): long enough to read a line, short enough that a queue
#: does not see the same picture the whole time it waits.
DEFAULT_BANNER_SECONDS = 8

#: The design tokens the Vue app renders with (FR-15.4), resolved per terminal
#: from its `RPOS Theme` (`utils/theme.py`, D-198). The house look is the
#: fallback, and lives there beside the resolution that reaches for it.


@frappe.whitelist(allow_guest=True, methods=["POST"])
def pair_device(code: str, device_name: str | None = None) -> dict:
	"""Bind this machine to the terminal the code names (`D-226`).

	This replaced a list of every terminal the cashier could reach. The list was
	one tap away from a till in Dammam selling on the Riyadh branch (`D-035`),
	and nothing in it stopped two machines from taking the same terminal.

	**`allow_guest`, exactly as the print agent pairs** (`D-212`). A machine
	being set up has nobody signed in on it, and cannot have: the PIN pad belongs
	to a terminal, so the terminal has to be known before anybody can sign in.
	Requiring a session here refused the cashier with *Login to access* at the
	one screen where logging in is not yet possible — which is what happened on
	the user's own till.

	**The code is the authorisation**, and it is a narrow one: eight digits
	issued by a manager on the profile, alive for ten minutes, spent on first
	use, and guessing held to the PIN pad's per-device lockout (`D-204`). What it
	buys is a token for *that* terminal and nothing else — no session, no
	permissions, and no sale until a cashier signs in with their own PIN.

	**POST, and pinned to it.** Frappe discards everything a GET writes, so the
	first cashier to pair got a token back, a terminal that had never been
	paired, and a refusal one line later. The code has no business in a URL
	either, where the web server's log and the browser's history outlive the ten
	minutes it is worth (the same reason the manager PIN travels in a body).
	"""
	return device.pair(code, device_name=device_name)


@frappe.whitelist(methods=["POST"])
def issue_device_code(pos_profile: str) -> dict:
	"""A pairing code for a terminal, for whoever may edit it — the desk button."""
	return device.issue_code(pos_profile)


@frappe.whitelist(methods=["POST"])
def unpair_device(pos_profile: str) -> dict:
	"""Free a terminal from the machine holding it — the desk button."""
	return device.unpair(pos_profile)


@frappe.whitelist()
def csrf_token() -> dict:
	"""The signed-in session's CSRF token, fetched at runtime.

	The page carries the token already, injected by Jinja. That is enough right
	up until the browser serves the HTML from its own cache — a page stored
	while nobody was signed in comes back with an empty token, and every write
	is refused before it leaves the machine. It looks exactly like a broken
	button, and it has now cost two rounds of debugging (D-030, D-031).

	Reading it back over a **GET** closes that off for good: a GET carries no
	token, so this cannot deadlock, and the answer is bound to the session
	cookie the browser already holds. Nothing is exposed — another origin can
	send the request but the same-origin policy stops it reading the reply, and
	a caller without a session gets nothing at all.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Sign in first."), frappe.PermissionError)

	# **Generated if the session has none** (`D-103`), through Frappe's own
	# helper rather than by reading the field.
	#
	# This used to read `session.data.csrf_token` and refuse when it was empty,
	# on the reasoning that Frappe issues one when a session starts. It does —
	# when a *page* is rendered. A session created by `login_manager.login_as`
	# over the API renders nothing, so a cashier who signed in with a PIN had a
	# perfectly good session carrying no token, and the first thing they tried
	# to do was refused with an instruction to sign out and sign in again — the
	# one action guaranteed not to help.
	return {"csrf_token": frappe.sessions.get_csrf_token()}


@frappe.whitelist()
def ping() -> dict:
	"""Connectivity probe for the sync engine (``09`` §2).

	Deliberately trivial: it must answer while the site is under load, because
	a slow answer is read as an outage and puts the terminal into offline mode.
	"""
	return {"status": "ok", "timestamp": now_datetime()}


@frappe.whitelist()
def load_pos_session(pos_profile: str, device_token: str | None = None) -> dict:
	"""The full terminal payload (07 §2).

	Refused unless this machine is the one paired with the terminal (`D-226`).
	Every till screen starts here, so this is the one gate that has to hold.
	"""
	profile = _profile(pos_profile)
	device.assert_this_device(profile, device_token)
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

	order_types = _order_types(profile)
	items, item_groups = _catalog(profile, order_types)

	return {
		"pos_profile": profile,
		"restaurant_section": section,
		# D-040 — a till at the door serves every hall, so the floor plan offers
		# all of them and the section on an order comes from its table.
		"sections": _sections(profile.branch),
		"branch": _branch(profile.branch),
		"screen_layout": _screen_layout(profile.screen_layout),
		"order_types": order_types,
		"payment_methods": _payment_methods(pos_profile),
		"active_shift": _active_shift(profile),
		# BR-044 — whether this cashier may ring a sale *now*: an open day and a
		# drawer of their own. Answered by the server so no screen has to work
		# it out, and so none of them can disagree with it (D-054).
		"can_sell": _can_sell(pos_profile),
		# D-071 — the inputs a device needs to reach the same total this server
		# does while the line is down: the tax rate, the cash-rounding step and
		# the rounding method. Shipped, never guessed (`09` §5).
		"pricing": totals_service.pricing_inputs(pos_profile),
		"items": items,
		"item_groups": item_groups,
		# D-076 — shipped with the menu, not fetched per item.
		#
		# The popup used to ask the server every time it opened, which made
		# "extra cheese" impossible during an outage and a round trip away from
		# the cashier the rest of the time. There are far fewer groups than
		# items, and the items are already here.
		"modifier_groups": _modifier_groups_for(items),
		"promotions": _promotions(profile.branch),
		# FR-2.9 — typing Arabic on a touch screen mid-rush is the slowest thing
		# a cashier does, and these are the notes a kitchen hears every day.
		"quick_notes": _quick_notes(),
		"permissions": get_pos_permission_set(),
		"theme": theme_service.tokens(profile),
		# `FR-13.1` — what the screen facing the room shows. The logo travels in
		# `theme`; the sentence and the banners are the restaurant's own
		# (`D-202`, `D-203`).
		"customer_display": _customer_display(),
		"lang": _lang(),
		# The header names the cashier on duty, and the home screen tells their
		# own orders from the rest of the floor.
		"user": frappe.session.user,
		"user_name": frappe.db.get_value("User", frappe.session.user, "full_name"),
		"server_time": now_datetime(),
	}


def _quick_notes() -> list[dict]:
	"""The notes a cashier taps instead of typing (FR-2.9).

	Both scopes in one list, tagged, because the screen shows item notes in one
	dialog and order notes in another and a second query would tell it nothing
	new.
	"""
	return frappe.get_all(
		"POS Quick Note",
		filters={"is_active": 1},
		fields=["name", "title", "title_ar", "scope"],
		order_by="sort_order asc, title asc",
	)


def _sections(branch: str | None) -> list[dict]:
	"""Every hall in this branch a table can be seated in (D-040).

	Not only the terminal's own: a restaurant with a men's hall and a family
	hall usually runs one till at the door for both, and the backend now judges
	a table by its branch.
	"""
	if not branch:
		return []

	return frappe.get_all(
		"Restaurant Section",
		filters={"branch": branch, "is_active": 1, "has_tables": 1},
		fields=["name", "title", "title_ar", "section_type"],
		order_by="sort_order asc, title asc",
	)


def _lang() -> str:
	"""The language this user reads, as ERPNext already knows it (FR-17.3).

	Only the two languages the app ships with are honoured. Anything else — a
	site defaulting to `de` because of an ERPNext setting nobody revisited —
	falls back to Arabic rather than rendering keys.
	"""
	supported = {"ar", "en"}
	lang = (frappe.db.get_value("User", frappe.session.user, "language") or "").split("-")[0]
	return lang if lang in supported else "ar"


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
			# The terminal's own theme, first in the resolution order (`FR-15.2`).
			"rpos_theme",
			# Which machine may load this terminal at all (`D-226`).
			"rpos_device_token_hash",
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
	"""FR-3.5 — the layout assigned to this terminal, with its buttons.

	`layout_mode` decides what the coordinates mean (`D-141`): in `flow` the
	till lays the buttons out in `idx` order and the grid fields are ignored, so
	arranging a menu is dragging rows in a table rather than inventing numbers.
	"""
	if not layout:
		return None

	doc = frappe.db.get_value(
		"POS Screen Layout",
		layout,
		["name", "title", "layout_mode", "grid_columns", "grid_rows", "background_color", "is_active"],
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
	active = frappe.get_all(
		"Restaurant Order Type", filters={"is_active": 1}, order_by="sort_order asc", pluck="name"
	)

	# A row pointing at an order type that no longer exists is not a
	# restriction, it is debris — from a force-delete, a partial import or a
	# restore. Counting it would leave the terminal showing nothing at all,
	# with no clue why, which is the worst possible failure for a till.
	permitted = {
		row.order_type
		for row in frappe.get_all(
			"POS Profile Order Type",
			filters={"parent": profile.name, "parenttype": "POS Profile"},
			fields=["order_type"],
		)
	} & set(active)

	rows = []
	for name in active:
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
				# D-038 — who owes the money, and so whether an open order may be
				# turned into this type. The screen greys the rest out with the
				# reason; the server refuses them regardless.
				"counterparty": config.counterparty,
				"send_to_kitchen_on": config.send_to_kitchen_on,
				"sort_order": config.sort_order,
				# FR-1.6 — a delivery platform's menu is priced above the dining
				# room's. Empty means the terminal's own list.
				"selling_price_list": config.selling_price_list,
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
	"""The terminal's methods, and which of them take notes.

	`is_cash` rides along because the payment screen offers round denominations
	only for cash (`D-124`), and a device that has lost the connection still has
	to take a fifty for a thirty-five bill. Reading it here means the answer is
	on the device before it is needed rather than at the moment it is not.
	"""
	from restaurant_pos.utils.payment import is_cash, is_credit_method

	rows = frappe.get_all(
		"POS Payment Method",
		filters={"parent": pos_profile, "parenttype": "POS Profile"},
		fields=["mode_of_payment", "default", "allow_in_returns"],
		order_by="idx",
	)
	for row in rows:
		row["is_cash"] = 1 if is_cash(row["mode_of_payment"]) else 0
		row["is_credit"] = 1 if is_credit_method(row["mode_of_payment"]) else 0
		# `D-256` — the method that spends a gift card, named by the server for
		# the reason the others are: a renamed method must not stop working.
		row["is_gift_card"] = 1 if is_gift_card_method(row["mode_of_payment"]) else 0

	return rows


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


def _can_sell(pos_profile: str) -> bool:
	"""BR-044 — the server's own answer, taken whole by every screen (D-054).

	Not re-derived here: `shift.may_sell` is the same call the endpoints make
	before they refuse, so the screen and the server cannot disagree.
	"""
	from restaurant_pos.utils.shift import may_sell

	return may_sell(pos_profile)


def _catalog(profile, order_types: list[dict]) -> tuple[list[dict], list[dict]]:
	"""The menu, assembled in a fixed number of queries regardless of its size.

	Prices, modifier groups and item groups are each fetched once and joined in
	memory. Looking any of them up per item is the N+1 pattern that would make
	login crawl on a real menu (``04`` §8).

	**Every price list the terminal can sell from is included**, not just the
	terminal's own: an order type may price its menu differently (FR-1.6), and
	the app is expected to keep working through an outage, so it cannot fetch
	the delivery prices later. That is one extra query per distinct list, and a
	shop has two or three.
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

	wanted = {row["selling_price_list"] for row in order_types if row.get("selling_price_list")}
	if profile.selling_price_list:
		wanted.add(profile.selling_price_list)

	#: {price_list: {item_code: rate}}
	by_list: dict[str, dict[str, float]] = {name: {} for name in wanted}
	if wanted:
		for row in frappe.get_all(
			"Item Price",
			filters={
				"price_list": ("in", list(wanted)),
				"selling": 1,
				"item_code": ("in", codes),
			},
			fields=["item_code", "price_list", "price_list_rate"],
		):
			by_list[row.price_list][row.item_code] = flt(row.price_list_rate)

	prices = by_list.get(profile.selling_price_list, {})
	picture = _setting("default_item_image")

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
		# **Every list, including the terminal's own** (`D-229`).
		#
		# This used to skip the terminal's list, on the reasoning that `rate`
		# already carries it and the common case should add nothing to the
		# payload. But the till reads `rates[list]` whenever the order type names
		# one — and an order type that names *the terminal's own list*, which is
		# the ordinary way to say "sell these at the usual prices", then found
		# nothing there. Every tile read "no price" and could not be tapped,
		# while the bill above them priced correctly, because the server resolves
		# this properly. The user met it mid-service, and closing the app
		# "fixed" it only until an order type was chosen again.
		#
		# One number per item per list is nothing next to a menu; a rule the
		# screen has to remember is not (`CLAUDE.md` §5.5).
		row.rates = {name: rates[row.item_code] for name, rates in by_list.items() if row.item_code in rates}
		row.modifier_groups = modifiers.get(row.item_code, [])
		row.display_name = row.pos_display_name_ar or row.item_name
		row.image = row.image or picture

	return items, _item_groups()


def _item_groups() -> list[dict]:
	# `image` is ERPNext's own field on the Item Group (`D-192`): the picture on the
	# group's tile, uploaded in the desk.
	groups = frappe.get_all(
		"Item Group",
		filters={"is_group": 0},
		fields=["name", "item_group_name", "parent_item_group", "default_production_center", "image"],
		order_by="name asc",
	)
	picture = _setting("default_group_image")
	for row in groups:
		row.image = row.image or picture
	return groups


def _customer_display() -> dict:
	"""What the screen facing the room shows (`FR-13.1`, `D-203`).

	Shipped with the menu because that window loads no session of its own — the
	till reads this and hands it across (`D-162`, `D-202`). So the banners keep
	turning through an outage, as long as the pictures themselves are in the
	browser's cache.

	A banner switched off stays in the list a manager reads and out of the one
	the guest sees: a seasonal offer comes back, and deleting it loses the file.
	"""
	settings = frappe.get_cached_doc("Restaurant POS Settings")
	return {
		"message": settings.idle_message or None,
		"seconds": cint(settings.banner_seconds) or DEFAULT_BANNER_SECONDS,
		"banners": [row.image for row in settings.banners if row.is_active and row.image],
	}


def _setting(field: str) -> str | None:
	"""One value from the settings page, empty read as nothing (`D-197`, `D-202`).

	The default pictures a dish or a group shows when it has none of its own, and
	the message the customer's screen carries while it waits.

	Filled in here, where every picture on the till passes, not in each tile that
	draws one: the menu's four grids, the screen layout's buttons and a line's
	detail all read `image`, and a fallback remembered in five places is one
	forgotten in the sixth (`CLAUDE.md` §5.5). And it rides in the payload the
	device keeps, so it holds offline. Left empty, the till draws its own icon.
	"""
	return frappe.db.get_single_value("Restaurant POS Settings", field) or None


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


def _modifier_groups_for(items: list[dict]) -> list[dict]:
	"""Every group this terminal's menu can reach (D-076).

	Scoped to the menu rather than the whole site: a chain's other branches sell
	things this till does not, and a payload is read on every sign-in.
	"""
	wanted = sorted({group for item in items for group in (item.get("modifier_groups") or [])})
	return get_modifier_groups(wanted) if wanted else []


@frappe.whitelist()
def get_modifier_groups(groups: list | str | None = None) -> list[dict]:
	"""Modifier groups with their options, for the item popup (FR-4.4)."""
	# Names no branch, so it asks for a till role itself (`D-208`).
	assert_pos_user()
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

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""A realistic restaurant, for demonstrating and exercising the system.

**Not shipped defaults.** `setup/defaults.py` runs on install and creates only
what every restaurant needs. Nothing here runs automatically: a real customer
must never find شيش طاووق on their menu because they installed the app.

Run it deliberately::

    bench --site your-site execute restaurant_pos.setup.demo.create_demo_data

Idempotent — anything already present is left alone, so it can be re-run after
adding to the menu.

What it builds: a five-station kitchen with printers and routing rules, a menu
of thirty dishes in six groups with Arabic names and real prices, modifier
groups wired to the dishes that need them, twelve tables, and a screen layout
the cashier actually uses.
"""

import hashlib

import frappe
from frappe import _

PREFIX = "RPOS"

# --------------------------------------------------------------------------- #
# Kitchen
# --------------------------------------------------------------------------- #

PRINTERS = [
	{"title": "طابعة الكاشير", "ip_address": "192.168.1.50"},
	{"title": "طابعة المشاوي", "ip_address": "192.168.1.51"},
	{"title": "طابعة المقالي", "ip_address": "192.168.1.52"},
	{"title": "طابعة البار", "ip_address": "192.168.1.53"},
]

PRODUCTION_CENTERS = [
	{"title": "Grill", "title_ar": "المشاوي", "printer": "طابعة المشاوي"},
	{"title": "Fryer", "title_ar": "المقالي", "printer": "طابعة المقالي"},
	{"title": "Bar", "title_ar": "البار", "printer": "طابعة البار"},
	{"title": "Cold Station", "title_ar": "القسم البارد", "printer": "طابعة المقالي"},
]

# --------------------------------------------------------------------------- #
# Menu — group -> production center, then the dishes
# --------------------------------------------------------------------------- #

#: The menu, and the colour each group's tile carries on the till.
#:
#: These are **muted** rather than the saturated defaults they started as
#: (`D-134`). Six full-strength tiles filling the working half of the screen is
#: a wall of signal with nothing to say — every one is shouting, so none of them
#: marks anything. Dropped in chroma they still separate at a glance, which is
#: all a category tile has to do, and the one saturated thing left on the screen
#: is the button that takes money.
#:
#: Colour lives here, in **data**, and not in a component: a hex in a component
#: is a lint error and freezes what a restaurant can change (`FR-15.5`).
MENU = [
	{
		"group": "Grills",
		"group_ar": "مشاوي",
		"centre": "Grill",
		"colour": "#8C2F2A",
		"items": [
			("شيش طاووق", 32.00),
			("كباب لحم", 38.00),
			("عرايس لحم", 28.00),
			("ريش غنم", 75.00),
			("مشاوي مشكل", 95.00),
		],
	},
	{
		"group": "Burgers",
		"group_ar": "برغر",
		"centre": "Fryer",
		"colour": "#A8551F",
		"items": [
			("برغر كلاسيك", 25.00),
			("برغر دجاج مقرمش", 23.00),
			("برغر لحم مزدوج", 35.00),
			("برغر بالجبن", 28.00),
		],
	},
	{
		"group": "Starters",
		"group_ar": "مقبلات",
		"centre": "Fryer",
		"colour": "#8A6B1D",
		"items": [
			("بطاطس مقلية", 12.00),
			("أصابع موزاريلا", 18.00),
			("حمص بالطحينة", 10.00),
			("متبل", 10.00),
			("سمبوسة لحم", 14.00),
		],
	},
	{
		"group": "Salads",
		"group_ar": "سلطات",
		"centre": "Cold Station",
		"colour": "#1F5C3D",
		"items": [
			("فتوش", 16.00),
			("تبولة", 14.00),
			("سيزر بالدجاج", 26.00),
			("سلطة خضراء", 12.00),
		],
	},
	{
		"group": "Drinks",
		"group_ar": "مشروبات",
		"centre": "Bar",
		"colour": "#2B4A86",
		"items": [
			("بيبسي", 8.00),
			("ماء", 3.00),
			("عصير برتقال طازج", 14.00),
			("ليمون بالنعناع", 15.00),
			("شاي أحمر", 6.00),
			("قهوة عربية", 10.00),
		],
	},
	{
		"group": "Desserts",
		"group_ar": "حلويات",
		"centre": "Cold Station",
		"colour": "#5F3574",
		"items": [
			("كنافة بالجبن", 22.00),
			("تشيز كيك", 24.00),
			("آيس كريم", 12.00),
			("أم علي", 20.00),
		],
	},
]

# --------------------------------------------------------------------------- #
# Modifiers — FR-4.1
# --------------------------------------------------------------------------- #

MODIFIER_GROUPS = [
	{
		"name": "Drink Size",
		"title": "Size",
		"title_ar": "الحجم",
		"selection_type": "single",
		"is_required": 1,
		"options": [
			("Small", "صغير", "none", 0, 1),
			("Medium", "وسط", "add", 3, 0),
			("Large", "كبير", "add", 6, 0),
		],
		"applies_to": ["Drinks"],
	},
	{
		"name": "Burger Extras",
		"title": "Extras",
		"title_ar": "إضافات",
		"selection_type": "multiple",
		"is_required": 0,
		"max_selections": 4,
		"options": [
			("Extra Cheese", "جبنة إضافية", "add", 4, 0),
			("Fried Egg", "بيض مقلي", "add", 3, 0),
			("Hot Sauce", "صوص حار", "none", 0, 0),
			("No Onion", "بدون بصل", "none", 0, 0),
			("Extra Patty", "قطعة لحم إضافية", "add", 12, 0),
		],
		"applies_to": ["Burgers"],
	},
	{
		"name": "Doneness",
		"title": "Doneness",
		"title_ar": "درجة الاستواء",
		"selection_type": "single",
		"is_required": 1,
		"options": [
			("Medium", "وسط", "none", 0, 1),
			("Well Done", "مستوي جيداً", "none", 0, 0),
			("Medium Rare", "نصف استواء", "none", 0, 0),
		],
		"applies_to": ["Grills"],
	},
]

#: Twelve tables: eight fours, two twos, two large.
TABLES = (
	[(str(number), 4) for number in range(1, 9)]
	+ [(str(number), 2) for number in (9, 10)]
	+ [(str(number), 8) for number in (11, 12)]
)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def create_demo_data(pos_profile: str | None = None) -> dict:
	"""Build the demo restaurant on top of an existing POS Profile."""
	profile = _profile(pos_profile)
	branch = frappe.db.get_value("Restaurant Section", profile.restaurant_section, "branch")

	price_list = _price_list(profile)

	created = {
		"price_list": [price_list],
		# Before the items: a menu priced without a tax template is a demo where
		# every receipt reads net = grand, which is what this site did until now.
		"vat_template": [_vat_template(profile)],
		"printers": _printers(branch),
		"production_centers": _production_centers(branch),
		"item_groups": _item_groups(),
		"items": _items(price_list),
		"routing_rules": _routing_rules(branch),
		"modifier_groups": _modifier_groups(),
		"tables": _tables(profile.restaurant_section),
		"screen_layout": _screen_layout(profile),
	}

	frappe.db.commit()
	return created


#: The demo prices its own menu rather than borrowing whatever list happens to
#: be on the terminal. A site that never ran ERPNext's setup wizard has no
#: selling price list at all (D-012), and the test suite creates and assigns its
#: own — so "whatever the profile points at" is not something to build on.
DEMO_PRICE_LIST = "RPOS Demo Selling"


def _price_list(profile) -> str:
	"""Create the demo's price list and point the terminal at it."""
	if not frappe.db.exists("Price List", DEMO_PRICE_LIST):
		frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": DEMO_PRICE_LIST,
				"currency": profile.currency or "SAR",
				"selling": 1,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)

	frappe.db.set_value("POS Profile", profile.name, "selling_price_list", DEMO_PRICE_LIST)
	return DEMO_PRICE_LIST


def _profile(pos_profile: str | None) -> frappe._dict:
	name = pos_profile or frappe.db.get_value("POS Profile", {}, "name")
	if not name:
		frappe.throw(_("Create a POS Profile before loading demo data."))

	profile = frappe.db.get_value(
		"POS Profile",
		name,
		["name", "restaurant_section", "selling_price_list", "company", "currency"],
		as_dict=True,
	)
	if not profile.restaurant_section:
		frappe.throw(_("POS Profile {0} has no Restaurant Section.").format(name))

	if not profile.selling_price_list:
		frappe.throw(_("POS Profile {0} has no selling price list.").format(name))

	return profile


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


#: The KSA rate. Written here because this is demo *data*, not code: no part of
#: the application knows what 15 means (`CLAUDE.md` §5.1). `totals.tax_rate_for`
#: reads whatever this template says, and a zero-rated outlet is a different
#: template rather than a different build.
VAT_RATE = 15
VAT_TEMPLATE = "KSA VAT 15%"

#: A placeholder VAT registration number for the demo, in the Saudi shape:
#: 15 digits beginning and ending with 3. Not a real registration.
DEMO_VAT_NUMBER = "300000000000003"


def _vat_template(profile) -> str:
	"""A 15% VAT template on **ERPNext's own** DocTypes (D-089).

	Nothing about tax is ours. `Sales Taxes and Charges Template` is ERPNext's,
	its screen is ERPNext's, and `POS Profile.taxes_and_charges` is ERPNext's
	field — `payment._create_sales_invoice` just reads it and hands the rows to
	the Sales Invoice controller. There is no RPOS tax model to keep in step.

	**Included in the price, which is the Saudi norm** (`D-091`): a menu says 32
	and the customer pays 32, of which 4.17 is VAT. Both sides of the till know
	it — `totals.compute` and its offline port each read
	`included_in_print_rate` and extract the tax rather than add it — and the
	discount comes off the grand total to match.
	"""
	company = profile.company

	# Before the early return below, not after it. Without a VAT number there is
	# no ZATCA QR, because tag 2 of the QR *is* the VAT number and one missing it
	# is invalid rather than lenient (`D-092`). Put after the return, this ran
	# only on a site that had never had the template — which is not the site
	# anybody is looking at.
	if not frappe.db.get_value("Company", company, "tax_id"):
		frappe.db.set_value("Company", company, "tax_id", DEMO_VAT_NUMBER)
		frappe.clear_cache(doctype="Company")

	name = frappe.db.get_value("Sales Taxes and Charges Template", {"title": VAT_TEMPLATE}, "name")
	if name:
		# A demo built before the inclusive decision carries an exclusive row,
		# and a demo where the menu price and the invoice disagree is worse than
		# no demo. Corrected in place rather than left for somebody to notice.
		for row in frappe.get_all(
			"Sales Taxes and Charges",
			filters={"parent": name, "parenttype": "Sales Taxes and Charges Template"},
			pluck="name",
		):
			frappe.db.set_value("Sales Taxes and Charges", row, "included_in_print_rate", 1)

		frappe.db.set_value("POS Profile", profile.name, "taxes_and_charges", name)
		return name

	abbr = frappe.db.get_value("Company", company, "abbr")
	parent = frappe.db.get_value(
		"Account", {"company": company, "account_name": "Duties and Taxes", "is_group": 1}, "name"
	)
	if not parent:
		frappe.throw(_("{0} has no 'Duties and Taxes' account group to file VAT under.").format(company))

	account = f"VAT {VAT_RATE}% - {abbr}"
	if not frappe.db.exists("Account", account):
		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": f"VAT {VAT_RATE}%",
				"parent_account": parent,
				"company": company,
				"account_type": "Tax",
				"tax_rate": VAT_RATE,
				"is_group": 0,
			}
		).insert(ignore_permissions=True)

	template = frappe.get_doc(
		{
			"doctype": "Sales Taxes and Charges Template",
			"title": VAT_TEMPLATE,
			"company": company,
			"is_default": 1,
			"taxes": [
				{
					"charge_type": "On Net Total",
					"account_head": account,
					"description": "ضريبة القيمة المضافة 15%",
					"rate": VAT_RATE,
					# Saudi menus show the price the customer pays (`D-091`).
					# `totals.tax_is_inclusive` reads this flag, and the till
					# extracts the tax from the price instead of adding to it.
					"included_in_print_rate": 1,
					"cost_center": frappe.db.get_value(
						"Cost Center", {"company": company, "is_group": 0}, "name"
					),
				}
			],
		}
	)
	template.insert(ignore_permissions=True)

	frappe.db.set_value("POS Profile", profile.name, "taxes_and_charges", template.name)
	return template.name


def _print_agent(branch: str) -> str:
	"""The one program in the restaurant that can reach a printer (D-084).

	Created with the printers rather than left for later: a printer with no
	agent is a printer nothing can send to, and a demo that quietly cannot print
	teaches the wrong shape of the system.
	"""
	existing = frappe.db.get_value("POS Print Agent", {"title": "وكيل الطباعة", "branch": branch})
	if existing:
		return existing

	agent = frappe.get_doc(
		{"doctype": "POS Print Agent", "title": "وكيل الطباعة", "branch": branch, "is_active": 1}
	)
	agent.insert(ignore_permissions=True)
	return agent.name


def _printers(branch: str) -> list[str]:
	agent = _print_agent(branch)
	created = []
	for spec in PRINTERS:
		existing = frappe.db.get_value("POS Printer", {"title": spec["title"], "branch": branch})
		if existing:
			# An older demo built these before agents existed; give them one
			# rather than leaving a printer nothing owns.
			if not frappe.db.get_value("POS Printer", existing, "print_agent"):
				frappe.db.set_value("POS Printer", existing, "print_agent", agent)
			continue

		doc = frappe.get_doc(
			{
				"doctype": "POS Printer",
				"title": spec["title"],
				"branch": branch,
				"print_agent": agent,
				"connection_type": "network",
				"ip_address": spec["ip_address"],
				"port": 9100,
				"printer_model": "epson",
				"paper_width": "80mm",
				"print_mode": "image",
				"cut_after_print": 1,
			}
		).insert(ignore_permissions=True)
		created.append(doc.name)

	return created


def _production_centers(branch: str) -> list[str]:
	created = []
	cashier_printer = frappe.db.get_value("POS Printer", {"title": "طابعة الكاشير", "branch": branch}, "name")

	for spec in PRODUCTION_CENTERS:
		if frappe.db.exists("Production Center", {"title": spec["title"], "branch": branch}):
			continue

		printer = frappe.db.get_value("POS Printer", {"title": spec["printer"], "branch": branch}, "name")
		doc = frappe.get_doc(
			{
				"doctype": "Production Center",
				"title": spec["title"],
				"title_ar": spec["title_ar"],
				"branch": branch,
				"printer": printer,
				# BR-072 — the cashier printer is the last resort.
				"fallback_printer": cashier_printer if cashier_printer != printer else None,
				"auto_print_on_send": 1,
			}
		).insert(ignore_permissions=True)
		created.append(doc.name)

	return created


def _item_groups() -> list[str]:
	root = frappe.db.get_value("Item Group", {"is_group": 1, "parent_item_group": ""}, "name")
	created = []

	for section in MENU:
		if frappe.db.exists("Item Group", section["group"]):
			continue

		doc = frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": section["group"],
				"parent_item_group": root,
				"is_group": 0,
			}
		).insert(ignore_permissions=True)
		created.append(doc.name)

	return created


def _items(price_list: str) -> list[str]:
	"""Dishes with Arabic names and prices.

	``is_stock_item = 0``: a prepared dish is not stock. Recipe-level depletion
	is the food-cost feature in `01_Project_Vision.md`, not something to fake
	with a stock item per dish.
	"""
	created = []

	for section in MENU:
		for arabic_name, price in section["items"]:
			code = _item_code(section["group"], arabic_name)

			if not frappe.db.exists("Item", code):
				frappe.get_doc(
					{
						"doctype": "Item",
						"item_code": code,
						"item_name": arabic_name,
						"pos_display_name_ar": arabic_name,
						"item_group": section["group"],
						"stock_uom": "Nos",
						"is_stock_item": 0,
						"is_sales_item": 1,
					}
				).insert(ignore_permissions=True)
				created.append(code)

			if not frappe.db.exists("Item Price", {"item_code": code, "price_list": price_list}):
				frappe.get_doc(
					{
						"doctype": "Item Price",
						"item_code": code,
						"price_list": price_list,
						"selling": 1,
						"price_list_rate": price,
					}
				).insert(ignore_permissions=True)

	return created


def _item_code(group: str, arabic_name: str) -> str:
	"""A stable ASCII code, because an item code is a key and not a label.

	`hash()` was the obvious choice and the wrong one: Python randomises string
	hashing per process, so every run of this loader invented a fresh set of
	codes and created the whole menu again. The site ended up with several
	copies of every dish, only the newest of them priced — which is exactly how
	a menu comes up saying "no price" for everything.
	"""
	digest = hashlib.md5(arabic_name.encode("utf-8")).hexdigest()
	return f"{PREFIX}-{group[:3].upper()}-{digest[:6].upper()}"


def _routing_rules(branch: str) -> list[str]:
	"""One rule per menu group — BR-070 level 2 territory.

	Set on the group rather than on each dish so a new dish is routed the moment
	it is added to the menu.
	"""
	created = []

	for section in MENU:
		centre = frappe.db.get_value(
			"Production Center", {"title": section["centre"], "branch": branch}, "name"
		)
		if not centre:
			continue

		if frappe.db.exists(
			"POS Printer Routing Rule",
			{"branch": branch, "item_group": section["group"], "production_center": centre},
		):
			continue

		doc = frappe.get_doc(
			{
				"doctype": "POS Printer Routing Rule",
				"branch": branch,
				"item_group": section["group"],
				"production_center": centre,
				"priority": 10,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		created.append(doc.name)

	return created


def _modifier_groups() -> list[str]:
	created = []

	for spec in MODIFIER_GROUPS:
		if not frappe.db.exists("POS Modifier Group", spec["name"]):
			doc = frappe.get_doc(
				{
					"doctype": "POS Modifier Group",
					"__newname": spec["name"],
					"title": spec["title"],
					"title_ar": spec["title_ar"],
					"selection_type": spec["selection_type"],
					"is_required": spec["is_required"],
					"max_selections": spec.get("max_selections", 0),
					"modifier_options": [
						{
							"title": title,
							"title_ar": title_ar,
							"price_effect": effect,
							"price_amount": amount,
							"is_default": is_default,
							"is_active": 1,
						}
						for title, title_ar, effect, amount, is_default in spec["options"]
					],
				}
			).insert(ignore_permissions=True)
			created.append(doc.name)

		_attach_modifiers(spec)

	return created


def _attach_modifiers(spec) -> None:
	"""FR-4.3 — link the group to every dish in the groups it applies to."""
	for group in spec["applies_to"]:
		for code in frappe.get_all("Item", filters={"item_group": group}, pluck="name"):
			if frappe.db.exists(
				"Modifier Group Assignment",
				{"parent": code, "parenttype": "Item", "modifier_group": spec["name"]},
			):
				continue

			item = frappe.get_doc("Item", code)
			item.append("pos_modifier_groups", {"modifier_group": spec["name"]})
			item.save(ignore_permissions=True)


def _tables(section: str) -> list[str]:
	"""Twelve tables laid out on a grid, ready for the Phase 4 canvas."""
	created = []

	for index, (number, capacity) in enumerate(TABLES):
		if frappe.db.exists("Restaurant Table", {"table_number": number, "section": section}):
			continue

		column, row = index % 4, index // 4
		doc = frappe.get_doc(
			{
				"doctype": "Restaurant Table",
				"table_number": number,
				"section": section,
				"capacity": capacity,
				"shape": "round" if capacity == 2 else "square",
				"status": "available",
				"pos_x": 80 + column * 220,
				"pos_y": 80 + row * 200,
				"width": 140 if capacity <= 4 else 220,
				"height": 140,
			}
		).insert(ignore_permissions=True)
		created.append(doc.name)

	return created


def _screen_layout(profile) -> str | None:
	"""A 4x3 grid of menu groups, assigned to the terminal (FR-3.1, FR-3.5)."""
	title = "قائمة المطعم"
	existing = frappe.db.get_value("POS Screen Layout", {"title": title}, "name")

	if not existing:
		buttons = []
		for index, section in enumerate(MENU):
			buttons.append(
				{
					"button_type": "item_group",
					"item_group": section["group"],
					"col_start": (index % 3) * 2 + 1,
					"col_span": 2,
					"row_start": (index // 3) * 2 + 1,
					"row_span": 2,
					"display_text": section["group"],
					"display_text_ar": section["group_ar"],
					"bg_color": section["colour"],
					"text_color": "#FFFFFF",
					"font_size": 20,
				}
			)

		existing = (
			frappe.get_doc(
				{
					"doctype": "POS Screen Layout",
					"title": title,
					"grid_columns": 6,
					"grid_rows": 4,
					"is_active": 1,
					"buttons": buttons,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	frappe.db.set_value("POS Profile", profile.name, "screen_layout", existing)

	cashier_printer = frappe.db.get_value("POS Printer", {"title": "طابعة الكاشير"}, "name")
	if cashier_printer:
		frappe.db.set_value("POS Profile", profile.name, "default_printer", cashier_printer)

	return existing

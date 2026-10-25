# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Everything the suite needs a site to already have.

Until now the tests leaned on whatever the demo site happened to contain — a
Branch somebody typed in the desk, a POS Profile made by hand, tables that grew
one at a time. That is why a test run was destructive: the suite and the demo
were the same data, and ERPNext's ``before_tests`` empties every price on the
site it touches.

This builds the same shapes from nothing, so the suite can own a throwaway site
and the demo can be left alone (``DECISIONS.md`` D-041).

Everything here is idempotent and named ``RPOS Test *`` or reused from
``setup/defaults.py``, so running it twice changes nothing and a human reading
the site can tell fixture from real data.
"""

import frappe
from frappe.utils import nowdate

from restaurant_pos.utils import quick_setup

BRANCH = "Riyadh"
SECTION_TITLE = "RPOS Test Hall"
PROFILE = "RPOS Test Terminal"

#: The suite's till is a paired device like any other (`D-226`): the session
#: refuses a machine that holds no token, so the fixtures hold one.
DEVICE_TOKEN = "rpos-test-device-token"

#: Enough to seat the table tests, and few enough to read in a failure message.
TABLE_COUNT = 6

#: The item every money assertion is written against (``tests/test_order.py``).
TEST_ITEM = "RPOS-TEST-BURGER"

#: The second item, for an order that reaches two stations (``tests/test_kitchen.py``).
SECOND_ITEM = "RPOS-TEST-FRIES"

#: The stations the kitchen and printing tests send to. They were leftovers of
#: an old smoke test on the first test site, which the suite then leaned on: a
#: site rebuilt from nothing had neither, and seventy tests failed on it.
STATIONS = ("RPOS Test Grill", "RPOS Test Fryer")

#: The group the suite's items sit in, under a parent group: the routing tests
#: route by group and by the group above it (``tests/test_routing.py``).
ITEM_GROUP, PARENT_GROUP = "RPOS Test Burgers", "RPOS Test Food"


#: The only sites this may run against. **An allow-list, because everything
#: below is destructive by design** — it grants roles to Administrator, rewrites
#: default data and plants fixture records. Naming the sites it may ruin is the
#: only safe direction for that list to point.
DISPOSABLE_SITES = frozenset({"test.localhost"})


def refuse_on_a_site_somebody_uses() -> None:
	"""Stop the suite before it touches a site that holds real data (`D-255`).

	**This was written after it happened.** Two runs went out as
	``bench --site rpos.localhost run-tests --module …`` — one character's worth
	of intent, aimed at the demo site instead of the test site — and thirty-two
	menu prices were gone before anything printed.

	**And the guard cannot save every case, which is the part worth knowing.**
	Frappe calls ``get_hooks("before_tests", app_name=app)``: with ``--app
	restaurant_pos`` that resolves to this hook alone, and the refusal below is
	complete. With ``--module`` there is no app to filter by, so **every**
	installed app's hook runs, in `apps.txt` order — and this app is last.
	ERPNext's runs first, and the first thing it does is::

	    frappe.db.sql("delete from `tabItem Price`")

	followed by a commit. By the time this function is reached the prices are
	already gone. So a `--module` run names its site and destroys it, and no code
	of ours can object in time. That is why the rule in `CLAUDE.md` §6.1 is to go
	through `scripts/wsl-check.sh`, which pins the site, rather than to type
	`bench` and trust the fingers.
	"""
	site = frappe.local.site
	if site in DISPOSABLE_SITES or frappe.conf.get("rpos_disposable_site"):
		return

	frappe.throw(
		f"Refusing to run tests on {site}: the suite rewrites default data, grants "
		f"Administrator every role and plants fixtures, and ERPNext's own hook empties "
		f"Item Price. Run them on {' or '.join(sorted(DISPOSABLE_SITES))}, or set "
		f'"rpos_disposable_site": 1 in the site_config.json of a site nobody minds '
		f"losing."
	)


def before_tests():
	"""Called by Frappe before the suite runs (``hooks.py``).

	**ERPNext's own hook is not inherited — but it is not always avoided.** It
	does two things: run the setup wizard on an empty site, and ``delete from
	`tabItem Price```. The first is broken on this pairing — Frappe 15.117's
	wizard stages null ``country`` and ``currency`` out of the arguments, and
	ERPNext 15.119 then fails on ``country.replace`` — and the second is what
	empties the menu. Neither is worth calling from here. A ``--module`` run
	calls it anyway, over our heads; `refuse_on_a_site_somebody_uses` says why.

	So the site must have had its setup wizard completed once, in a browser.
	That is a person's decision anyway: the company name, the chart of accounts
	and the fiscal year are business data, not fixtures.
	"""
	refuse_on_a_site_somebody_uses()
	_close_drawers_as_production_does()

	if not frappe.db.a_row_exists("Company"):
		frappe.throw(
			"This site has no Company. Open it in a browser and finish the ERPNext "
			"setup wizard once, then run the tests again."
		)

	_enable_all_roles_for_admin()

	from restaurant_pos.setup.defaults import create_default_data

	create_default_data()

	company = _company()
	branch = _branch(company)
	section = _section(branch)
	_tables(section)
	_pos_profile(company, section)
	_item_groups()
	_test_item()
	_test_item(SECOND_ITEM, "RPOS Test Fries", "بطاطس الاختبار")
	for title in STATIONS:
		_station(title, branch)

	_pin_rounding()

	# BR-024 rounds to the nearest 0.05, and the step is read from the Currency
	# record. `create_default_data` has just written it; the cached copy this
	# process already read has not caught up, and a stale zero rounds every bill
	# to whole riyals.
	frappe.clear_cache()

	frappe.db.commit()


def _close_drawers_as_production_does() -> None:
	"""Keep ERPNext's drawer closing from committing the test that called it.

	Submitting a `POS Closing Entry` calls `consolidate_pos_invoices`. Ours lists
	no invoices (`D-022`), so in production it merges nothing — but under
	`frappe.flags.in_test` an empty list means **every** unmerged POS Invoice on
	the site, and `create_merge_logs` ends in `finally: frappe.db.commit()`,
	merged or not. So every test that closed a drawer committed everything it had
	made, and the test site kept it (1517 orders once, `D-397`).

	Patched here, once for the whole run, because `before_tests` runs in the
	process the tests run in — not in each test that closes a drawer, where the
	one that forgets is the one that leaks. ERPNext's own code still runs; only
	the test-only pull and the commit are taken out. Nothing stops the patch: the
	process ends with the run.
	"""
	from unittest.mock import patch

	from erpnext.accounts.doctype.pos_closing_entry import pos_closing_entry
	from erpnext.accounts.doctype.pos_invoice_merge_log import pos_invoice_merge_log

	consolidate = pos_invoice_merge_log.consolidate_pos_invoices

	def consolidate_without_commit(pos_invoices=None, closing_entry=None):
		with (
			patch.object(pos_invoice_merge_log, "get_all_unconsolidated_invoices", return_value=[]),
			patch.object(frappe.db, "commit"),
		):
			return consolidate(pos_invoices, closing_entry)

	patch.object(pos_closing_entry, "consolidate_pos_invoices", consolidate_without_commit).start()


def _pin_rounding() -> None:
	"""Decide the tie, so a money assertion is not at the mercy of a setting.

	BR-024 rounds to the nearest 0.05 and says nothing about a bill that lands
	exactly halfway — 10.025 is 2.5 halalas from both neighbours. Frappe decides
	that with ``System Settings.rounding_method``, and the two sites we run on
	answered differently: one gave 10.00, the other 10.05.

	Neither is wrong, and it cannot make the screen disagree with the invoice —
	both go through the same helper. But a test that asserts a figure has to
	know which answer it is asserting, so the suite pins it. A restaurant is
	free to set the other; what it must not do is have the two disagree.
	"""
	frappe.db.set_single_value("System Settings", "rounding_method", "Banker's Rounding")


def _test_item(code: str = TEST_ITEM, name: str = "RPOS Test Burger", name_ar: str = "برغر الاختبار") -> str:
	"""An item the suite sells.

	Its price is not set here: ``tests/test_order.py`` owns the price list and
	the rate, so an assertion about arithmetic never depends on a fixture.
	"""
	if frappe.db.exists("Item", code):
		return code

	frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": code,
			"item_name": name,
			"pos_display_name_ar": name_ar,
			"item_group": ITEM_GROUP,
			"stock_uom": "Nos",
			"is_stock_item": 0,
			"is_sales_item": 1,
			"include_item_in_manufacturing": 0,
		}
	).insert(ignore_permissions=True)
	return code


def _item_groups() -> None:
	root = frappe.db.get_value("Item Group", {"is_group": 1, "parent_item_group": ""}, "name")
	for name, parent, is_group in ((PARENT_GROUP, root, 1), (ITEM_GROUP, PARENT_GROUP, 0)):
		if not frappe.db.exists("Item Group", name):
			frappe.get_doc(
				{
					"doctype": "Item Group",
					"item_group_name": name,
					"parent_item_group": parent,
					"is_group": is_group,
				}
			).insert(ignore_permissions=True)


def _station(title: str, branch: str) -> str:
	"""A kitchen station with a screen and no printer: the tests give it one when they need it."""
	existing = frappe.db.get_value("Production Center", {"title": title, "branch": branch}, "name")
	if existing:
		return existing

	return (
		frappe.get_doc(
			{
				"doctype": "Production Center",
				"title": title,
				"title_ar": title,
				"branch": branch,
				"has_kds": 1,
				"kds_display_id": title.lower().replace(" ", "-"),
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _enable_all_roles_for_admin() -> None:
	"""What ERPNext's hook does that is worth having.

	The suite signs in as its own cashiers for the permission tests (D-026), but
	Administrator still has to be able to reach every DocType to build the
	fixtures above.
	"""
	from frappe.desk.page.setup_wizard.setup_wizard import add_all_roles_to

	add_all_roles_to("Administrator")


def _company() -> str:
	company = frappe.db.get_value("Company", {}, "name")
	if not company:
		frappe.throw("No Company on this site; ERPNext's setup did not complete.")
	return company


def _branch(company: str) -> str:
	"""A branch, with the fields ``setup/install.py`` makes mandatory on it.

	`Branch` is ERPNext's, extended by our custom fields — so a fixture cannot
	just name it; it has to answer for the warehouse and cost centre the branch
	sells and books through, the same as a real one.
	"""
	if frappe.db.exists("Branch", BRANCH):
		return BRANCH

	basics = quick_setup.company_basics(company)
	frappe.get_doc(
		{
			"doctype": "Branch",
			"branch": BRANCH,
			"company": company,
			"default_warehouse": basics.warehouse,
			"default_cost_center": basics.cost_center,
		}
	).insert(ignore_permissions=True)
	return BRANCH


def _section(branch: str) -> str:
	existing = frappe.db.get_value("Restaurant Section", {"title": SECTION_TITLE}, "name")
	if existing:
		return existing

	return (
		frappe.get_doc(
			{
				"doctype": "Restaurant Section",
				"title": SECTION_TITLE,
				"title_ar": "صالة الاختبار",
				"branch": branch,
				"section_type": "dine_in",
				"has_tables": 1,
				"is_active": 1,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _tables(section: str) -> None:
	for number in range(1, TABLE_COUNT + 1):
		if frappe.db.exists("Restaurant Table", {"section": section, "table_number": str(number)}):
			continue

		frappe.get_doc(
			{
				"doctype": "Restaurant Table",
				"table_number": str(number),
				"section": section,
				"capacity": 4,
				"status": "available",
				"is_active": 1,
			}
		).insert(ignore_permissions=True)


def _pos_profile(company: str, section: str) -> str:
	"""The terminal the suite sells from.

	Its price list is left unset on purpose: ``tests/test_order.py`` creates one
	with known rates and points the profile at it, so a money assertion never
	depends on what the site happens to be selling from.
	"""
	if frappe.db.exists("POS Profile", PROFILE):
		frappe.db.set_value("POS Profile", PROFILE, "restaurant_section", section)
		_pair_test_device(PROFILE)
		return PROFILE

	basics = quick_setup.company_basics(company)

	profile = frappe.get_doc(
		{
			"doctype": "POS Profile",
			"name": PROFILE,
			"company": company,
			"currency": frappe.db.get_value("Company", company, "default_currency"),
			"warehouse": basics.warehouse,
			"write_off_account": basics.write_off,
			"write_off_cost_center": basics.cost_center,
			"write_off_limit": 1,
			"customer": quick_setup.walk_in_customer(),
			"restaurant_section": section,
			"payments": [{"mode_of_payment": quick_setup.cash_method(company), "default": 1}],
		}
	)
	profile.insert(ignore_permissions=True)
	_pair_test_device(profile.name)
	return profile.name


def _pair_test_device(profile: str) -> None:
	from restaurant_pos.utils import pairing

	frappe.db.set_value(
		"POS Profile",
		profile,
		{
			"rpos_device_token_hash": pairing.digest(DEVICE_TOKEN),
			"rpos_device_name": "the suite",
		},
		update_modified=False,
	)


def open_test_shift(profile: str = PROFILE) -> str:
	"""An open day **and** an open drawer — BR-044 refuses a sale without both.

	The day alone was enough until `D-054`: closing a till hands the money back
	while the day carries on, and a sale after that count belongs to no drawer.
	"""
	branch = frappe.db.get_value(
		"Restaurant Section", frappe.db.get_value("POS Profile", profile, "restaurant_section"), "branch"
	)

	shift = frappe.db.get_value("Restaurant Shift", {"branch": branch, "status": "open"}, "name")
	if not shift:
		shift = (
			frappe.get_doc(
				{
					"doctype": "Restaurant Shift",
					"title": "RPOS Test Shift",
					"branch": branch,
					"shift_date": nowdate(),
					"shift_type": "full_day",
					"status": "open",
					"opened_by": "Administrator",
					"opened_at": frappe.utils.now_datetime(),
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	frappe.db.set_value("POS Profile", profile, "restaurant_shift", shift)

	from restaurant_pos.utils import shift as shift_service

	shift_service.open_till(pos_profile=profile)
	return shift

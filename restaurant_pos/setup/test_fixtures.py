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

BRANCH = "Riyadh"
SECTION_TITLE = "RPOS Test Hall"
PROFILE = "RPOS Test Terminal"
COMPANY_ABBR_FALLBACK = "RTC"

#: Enough to seat the table tests, and few enough to read in a failure message.
TABLE_COUNT = 6


def before_tests():
	"""Called by Frappe before the suite runs (``hooks.py``).

	**ERPNext's own hook is not called.** It does two things: run the setup
	wizard on an empty site, and ``delete from `tabItem Price```. The first is
	broken on this pairing — Frappe 15.117's wizard stages null ``country`` and
	``currency`` out of the arguments, and ERPNext 15.119 then fails on
	``country.replace`` — and the second is what emptied the demo menu every
	time the suite ran. Neither is worth inheriting.

	So the site must have had its setup wizard completed once, in a browser.
	That is a person's decision anyway: the company name, the chart of accounts
	and the fiscal year are business data, not fixtures.
	"""
	if not frappe.db.a_row_exists("Company"):
		frappe.throw(
			"This site has no Company. Open it in a browser and finish the ERPNext "
			"setup wizard once, then run the tests again."
		)

	_enable_all_roles_for_admin()

	from restaurant_pos.setup.defaults import create_default_data

	create_default_data()

	company = _company()
	branch = _branch()
	section = _section(branch)
	_tables(section)
	_pos_profile(company, section)

	frappe.db.commit()


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


def _branch() -> str:
	if not frappe.db.exists("Branch", BRANCH):
		frappe.get_doc({"doctype": "Branch", "branch": BRANCH}).insert(ignore_permissions=True)
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
		return PROFILE

	abbr = frappe.db.get_value("Company", company, "abbr") or COMPANY_ABBR_FALLBACK

	profile = frappe.get_doc(
		{
			"doctype": "POS Profile",
			"name": PROFILE,
			"company": company,
			"currency": frappe.db.get_value("Company", company, "default_currency"),
			"warehouse": _warehouse(company),
			"write_off_account": _account(company, "Write Off", abbr),
			"write_off_cost_center": _cost_center(company, abbr),
			"write_off_limit": 1,
			"customer": _walk_in_customer(),
			"restaurant_section": section,
			"payments": [{"mode_of_payment": _cash_method(company), "default": 1}],
		}
	)
	profile.insert(ignore_permissions=True)
	return profile.name


def _warehouse(company: str) -> str:
	warehouse = frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")
	if not warehouse:
		frappe.throw("No Warehouse on this site; ERPNext's setup did not complete.")
	return warehouse


def _account(company: str, name: str, abbr: str) -> str:
	account = frappe.db.get_value("Account", f"{name} - {abbr}", "name")
	if account:
		return account

	# Fall back to any leaf expense account rather than inventing one: the
	# chart of accounts belongs to ERPNext's setup, not to a fixture.
	account = frappe.db.get_value(
		"Account", {"company": company, "is_group": 0, "root_type": "Expense"}, "name"
	)
	if not account:
		frappe.throw("No expense account on this site; ERPNext's setup did not complete.")
	return account


def _cost_center(company: str, abbr: str) -> str:
	center = frappe.db.get_value("Cost Center", f"Main - {abbr}", "name")
	return center or frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")


def _walk_in_customer() -> str:
	name = "RPOS Walk-in"
	if not frappe.db.exists("Customer", name):
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": name,
				"customer_type": "Individual",
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
				"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
			}
		).insert(ignore_permissions=True)
	return name


def _cash_method(company: str) -> str:
	"""Cash, with an account for this company, so a POS invoice can settle."""
	if not frappe.db.exists("Mode of Payment", "Cash"):
		frappe.get_doc({"doctype": "Mode of Payment", "mode_of_payment": "Cash", "type": "Cash"}).insert(
			ignore_permissions=True
		)

	method = frappe.get_doc("Mode of Payment", "Cash")
	if not any(row.company == company for row in method.accounts):
		account = frappe.db.get_value(
			"Account", {"company": company, "account_type": "Cash", "is_group": 0}, "name"
		) or frappe.db.get_value(
			"Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name"
		)

		if account:
			method.append("accounts", {"company": company, "default_account": account})
			method.save(ignore_permissions=True)

	return "Cash"


def open_test_shift(profile: str = PROFILE) -> str:
	"""An open shift for the terminal — BR-044 refuses every sale without one."""
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
	return shift

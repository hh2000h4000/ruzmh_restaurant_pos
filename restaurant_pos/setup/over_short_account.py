# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Where a drawer's shortage or overage is written off, when the accountant says so (`D-357`).

A drawer that counts out short has money missing from the cash account the
books say is there. **The till does not decide what that is**: Toast, Square
and Foodics report it and leave it to the accountant, and so does Vitec where
the owner learned the trade — a shortage may be charged to the cashier, written
off, or found to be a float nobody counted. This is the account for the second
of those, shipped the way the waste account is (`D-315`): created once, and
never overwritten — an account a restaurant chose in the settings stays chosen.
"""

import frappe

from restaurant_pos.utils.company import site_company

ACCOUNT_NAME = "عجز وزيادة الصندوق"

SETTINGS = "Restaurant POS Settings"


def setup(company: str | None = None) -> str | None:
	"""Make the account if it is missing, and name it in the settings if they name none."""
	chosen = frappe.db.get_single_value(SETTINGS, "over_short_account")
	if chosen:
		return chosen

	company = site_company(company)
	if not company:
		return None

	account = _ensure_account(company)
	if account:
		frappe.db.set_single_value(SETTINGS, "over_short_account", account)
	return account


def _ensure_account(company: str) -> str | None:
	abbr = frappe.db.get_value("Company", company, "abbr")
	name = f"{ACCOUNT_NAME} - {abbr}"
	if frappe.db.exists("Account", name):
		return name

	# With the running costs, not beside cost of sales: a till shortage is not
	# the cost of anything sold.
	parent = frappe.db.get_value(
		"Account",
		{
			"company": company,
			"is_group": 1,
			"root_type": "Expense",
			"account_name": ("in", ["Indirect Expenses", "مصروفات غير مباشرة", "المصروفات غير المباشرة"]),
		},
		"name",
	)
	if not parent:
		beside = frappe.get_cached_value("Company", company, "default_expense_account")
		parent = frappe.db.get_value("Account", beside, "parent_account") if beside else None
	if not parent:
		# A chart built by hand; guessing a place in it is worse than creating nothing.
		return None

	return (
		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": ACCOUNT_NAME,
				"parent_account": parent,
				"company": company,
				"root_type": "Expense",
				"is_group": 0,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Where a returned dish that was thrown away is charged (`D-315`).

A burger sent back is not put back in the fridge. Its ingredients were used, so
the stock ledger is right to leave them out — but their cost is not the cost of
anything *sold*: the guest got their money back. Left in cost of sales, waste
hides inside the food cost of the dishes that did sell, and nobody can see how
much of it there was. Foodics reports it apart from returns for the same reason.

So the posting moves that cost from cost of sales to this account, and the
account is shipped, the way the gift cards' liability and the drawer's cash
accounts are (`D-246`, `D-256`): created once, and never overwritten — an
account a restaurant chose in the settings stays chosen.
"""

import frappe

from restaurant_pos.utils.company import site_company

ACCOUNT_NAME = "هدر الطعام"

SETTINGS = "Restaurant POS Settings"


def setup(company: str | None = None) -> str | None:
	"""Make the account if it is missing, and name it in the settings if they name none."""
	chosen = frappe.db.get_single_value(SETTINGS, "waste_account")
	if chosen:
		return chosen

	company = site_company(company)
	if not company:
		return None

	account = _ensure_account(company)
	if account:
		frappe.db.set_single_value(SETTINGS, "waste_account", account)
	return account


def _ensure_account(company: str) -> str | None:
	abbr = frappe.db.get_value("Company", company, "abbr")
	name = f"{ACCOUNT_NAME} - {abbr}"
	if frappe.db.exists("Account", name):
		return name

	# Beside cost of sales, wherever this chart keeps it: waste is read against
	# the food cost it was taken out of.
	beside = frappe.get_cached_value("Company", company, "default_expense_account")
	parent = frappe.db.get_value("Account", beside, "parent_account") if beside else None
	if not parent:
		# A company with no cost-of-sales account was set up by hand; guessing a
		# place in its chart is worse than creating nothing.
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

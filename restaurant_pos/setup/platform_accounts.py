# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Where what a delivery platform owes is kept (`D-319`).

An order from HungerStation is paid: the guest paid the platform. What the
restaurant is waiting for is the platform's transfer — so the sale is settled
with a payment method named after the platform, and that method points at an
account that holds what the platform owes. The accountant reads the balance off
the account, and clears it with one entry when the transfer lands: bank and
commission against it. Odoo's payment methods carry an outstanding account for
the same reason.

Shipped the way the gift cards' liability and the waste account are (`D-256`,
`D-315`): one account per shipped platform, made once, and never overwritten —
a method that already names an account for the company keeps it. A method a
restaurant makes for another platform gets its account in ERPNext's own
Mode of Payment form, like any other.
"""

import frappe

from restaurant_pos.setup.defaults import DELIVERY_APPS, ZATCA_MEANS_CREDIT, fill_zatca_means
from restaurant_pos.utils.company import site_company

ACCOUNT_NAME = "مستحقات {0}"


def setup(company: str | None = None) -> None:
	company = site_company(company)
	if not company:
		return

	for app in DELIVERY_APPS:
		if not frappe.db.exists("Mode of Payment", app["title"]):
			continue

		mode = frappe.get_doc("Mode of Payment", app["title"])
		if any(row.company == company for row in mode.accounts):
			continue

		account = _ensure_account(company, ACCOUNT_NAME.format(app["title_ar"]))
		if not account:
			continue

		mode.append("accounts", {"company": company, "default_account": account})
		# A method made before the ZATCA app was installed has no code, and saving
		# it would be refused for the field that app made mandatory (`D-306`).
		fill_zatca_means(mode, ZATCA_MEANS_CREDIT)
		mode.save(ignore_permissions=True)


def _ensure_account(company: str, account_name: str) -> str | None:
	abbr = frappe.db.get_value("Company", company, "abbr")
	name = f"{account_name} - {abbr}"
	if frappe.db.exists("Account", name):
		return name

	# Beside the customers' receivable, wherever this chart keeps it — but not a
	# Receivable itself: that type asks for a customer on every line, and the
	# platform is not billed, it is waited for.
	beside = frappe.get_cached_value("Company", company, "default_receivable_account")
	parent = frappe.db.get_value("Account", beside, "parent_account") if beside else None
	if not parent:
		# A chart set up by hand: guessing a place in it is worse than making nothing.
		return None

	return (
		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": account_name,
				"parent_account": parent,
				"company": company,
				"root_type": "Asset",
				"is_group": 0,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)

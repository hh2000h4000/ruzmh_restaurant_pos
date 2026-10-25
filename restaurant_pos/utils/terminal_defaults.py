# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""A terminal's ERPNext fields, filled from its branch (`D-400`).

ERPNext asks a `POS Profile` for a company, a currency, a warehouse, a write-off
account and cost centre, a customer, a price list, a tax template and a payment
method. A manager adding a till knows the branch and nothing else, and every one
of those answers already follows from it: the branch names its company,
warehouse and cost centre, and the company names the rest.

So the form asks for the branch, and this fills **only what is empty**. A value
somebody chose is never replaced — a terminal set apart from its branch on
purpose stays apart (`D-392`, decision 4 of the plan).

`POS Profile.before_validate`, so the fields are filled before Frappe checks
which of them are required.

Refs: D-337, D-345, D-392, D-400
"""

import frappe
from frappe import _

from restaurant_pos.utils import quick_setup
from restaurant_pos.utils.terminal_branch import branch_of_doc


def fill_from_branch(doc, method=None) -> None:
	branch = branch_of_doc(doc)
	if not branch:
		# Said here, before ERPNext's own checks: without a branch nothing below
		# can be filled, and its first complaint would be the payment methods.
		frappe.throw(_("Choose the branch this device sells in."), frappe.MandatoryError)

	home = frappe.db.get_value(
		"Branch", branch, ["company", "default_warehouse", "default_cost_center"], as_dict=True
	)
	if not doc.company:
		doc.company = home.company
	company = doc.company
	if not company:
		return

	if not doc.warehouse:
		doc.warehouse = home.default_warehouse
	if not doc.currency:
		doc.currency = frappe.db.get_value("Company", company, "default_currency")
	if doc.get("write_off_limit") in (None, ""):
		doc.write_off_limit = 1

	if not (doc.warehouse and doc.write_off_account and doc.write_off_cost_center):
		basics = quick_setup.company_basics(company)
		doc.warehouse = doc.warehouse or basics.warehouse
		doc.write_off_account = doc.write_off_account or basics.write_off
		doc.write_off_cost_center = (
			doc.write_off_cost_center or home.default_cost_center or basics.cost_center
		)

	if not doc.customer:
		doc.customer = quick_setup.walk_in_customer()
	if not doc.selling_price_list:
		doc.selling_price_list = quick_setup._menu_price_list()
	if not doc.taxes_and_charges:
		doc.taxes_and_charges = default_tax_template(company)
	if not doc.payments:
		doc.append("payments", {"mode_of_payment": quick_setup.cash_method(company), "default": 1})


#: What the device form fills the moment a branch is chosen (`D-400`).
FILLED = (
	"company",
	"currency",
	"warehouse",
	"write_off_account",
	"write_off_cost_center",
	"write_off_limit",
	"customer",
	"selling_price_list",
	"taxes_and_charges",
)


def defaults_for(branch: str) -> dict:
	"""The answers a device of ``branch`` gets — worked out by the same fill the save runs.

	The form asks for them as soon as the branch is picked: Frappe checks the
	required fields in the browser before the save reaches the server, so a fill
	that ran only on save never ran from the form at all.
	"""
	doc = frappe.new_doc("POS Profile")
	doc.rpos_branch = branch
	fill_from_branch(doc)
	answers = {field: doc.get(field) for field in FILLED}
	answers["payments"] = [
		{"mode_of_payment": row.mode_of_payment, "default": row.default} for row in doc.payments
	]
	return answers


def default_tax_template(company: str) -> str | None:
	"""The template the company marks default — never a guessed one: tax is not invented here."""
	return frappe.db.get_value(
		"Sales Taxes and Charges Template", {"company": company, "is_default": 1, "disabled": 0}, "name"
	)

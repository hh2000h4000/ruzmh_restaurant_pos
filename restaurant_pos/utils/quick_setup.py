# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Quick setup: from an installed app to a till that can sell, in one form (`D-307`).

The install ships what every restaurant shares — roles, permission sets, order
types, print templates, payment methods. What it cannot ship is what is the
customer's own: their branch, its halls and tables, the terminal at the
counter. Those hang off the company's warehouse, cost centre and accounts,
which differ on every site, so made silently on install they would be wrong
and in the way.

So they are asked for, the way Odoo's "New Shop" wizard and Toast's setup
checklist ask: a few answers, and everything they imply is made correctly —
the branch on the company's own warehouse and cost centre, the sections the
restaurant actually has, tables in the hall, and a terminal that can take cash.
A pairing code comes back at the end, because the next thing anybody does is
pair the till.
"""

import frappe
from frappe import _
from frappe.utils import cint

from restaurant_pos.setup.defaults import fill_zatca_means

#: The halls a restaurant may have, in the order the till lists them.
SECTIONS = (
	("dine_in", "Dining Hall", "الصالة"),
	("takeaway", "Takeaway", "السفري"),
	("delivery", "Delivery", "التوصيل"),
)

#: Tables a dining hall gets unless the form says otherwise — and at most.
DEFAULT_TABLES = 10
MAX_TABLES = 200

#: UN/EDIFACT 4461 "In cash", for a site with the ZATCA app (`D-306`).
ZATCA_MEANS_CASH = "10"

WALK_IN_CUSTOMER = "RPOS Walk-in"


def run(values: dict) -> dict:
	"""Make the branch, its sections and tables, and a terminal; return what was made."""
	values = frappe._dict(values)
	company = values.company or frappe.defaults.get_user_default("Company")
	if not company or not frappe.db.exists("Company", company):
		frappe.throw(_("Choose the company this branch belongs to."))

	branch_name = (values.branch or "").strip()
	if not branch_name:
		frappe.throw(_("Give the branch a name."))
	if frappe.db.exists("Branch", branch_name):
		frappe.throw(_("A branch called {0} already exists. Choose another name.").format(branch_name))

	terminal = (values.terminal or "").strip()
	if not terminal:
		frappe.throw(_("Give the cashier terminal a name."))
	if frappe.db.exists("POS Profile", terminal):
		frappe.throw(_("A terminal called {0} already exists. Choose another name.").format(terminal))

	wanted = [kind for kind, _title, _title_ar in SECTIONS if cint(values.get(kind))]
	if not wanted:
		frappe.throw(_("Choose at least one: dining hall, takeaway or delivery."))

	tables = cint(values.tables) if values.tables not in (None, "") else DEFAULT_TABLES
	if "dine_in" in wanted and not 1 <= tables <= MAX_TABLES:
		frappe.throw(_("A dining hall needs between 1 and {0} tables.").format(MAX_TABLES))

	# Before the branch, which starts the only way the site's setting lets it
	# (`D-337`): made first, it would be forced to refuse on a site that is
	# about to allow negative stock.
	allowed_now = _let_stock_go_below_zero()
	branch = _branch(branch_name, company)
	sections = {kind: _section(branch, kind) for kind in wanted}
	if "dine_in" in sections:
		_tables(sections["dine_in"], tables)

	# The terminal's home is the hall if there is one: a table-less order still
	# belongs to a section, and the hall is where most of them are rung.
	home = sections.get("dine_in") or next(iter(sections.values()))
	profile = _terminal(terminal, company, home, values.price_list, values.taxes_and_charges)

	from restaurant_pos.utils import device

	code = device.issue_code(profile)
	return {
		"negative_stock_allowed": allowed_now,
		"branch": branch,
		"sections": list(sections.values()),
		"tables": tables if "dine_in" in sections else 0,
		"pos_profile": profile,
		"pairing_code": code["code"],
		"minutes": code["minutes"],
	}


def _let_stock_go_below_zero() -> bool:
	"""Tick ERPNext's Allow Negative Stock, and say whether this did it (`D-326`).

	**A restaurant's stock goes below zero every week, and its posting must not
	stop for it.** A dish is never refused for its ingredients at the till
	(`D-321`), so a kitchen that enters its deliveries late sells what the
	ledger does not hold yet — and with this off, that evening's stock is not
	posted until somebody enters them. On, the shortfall is valued at the last
	known rate and corrected by the purchase when it arrives; nothing is lost
	(`docs/14` §5.1, measured). The owner's call, for every new restaurant.

	Left alone where it is already on, and said in the result where it is not:
	it is a setting of the whole site, not of this branch.
	"""
	if cint(frappe.db.get_single_value("Stock Settings", "allow_negative_stock")):
		return False
	frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)
	return True


def company_basics(company: str) -> frappe._dict:
	"""What a branch and a terminal of ``company`` hang off — read from ERPNext's own setup."""
	abbr = frappe.db.get_value("Company", company, "abbr")
	warehouse = frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")
	if not warehouse:
		frappe.throw(_("{0} has no warehouse yet. Finish ERPNext's setup first.").format(company))

	cost_center = frappe.db.get_value("Cost Center", f"Main - {abbr}", "name") or frappe.db.get_value(
		"Cost Center", {"company": company, "is_group": 0}, "name"
	)

	# Any leaf expense account rather than an invented one: the chart of
	# accounts is ERPNext's, not this app's.
	write_off = frappe.db.get_value("Account", f"Write Off - {abbr}", "name") or frappe.db.get_value(
		"Account", {"company": company, "is_group": 0, "root_type": "Expense"}, "name"
	)
	if not write_off:
		frappe.throw(_("{0} has no expense account yet. Finish ERPNext's setup first.").format(company))

	return frappe._dict(warehouse=warehouse, cost_center=cost_center, write_off=write_off)


def walk_in_customer() -> str:
	if not frappe.db.exists("Customer", WALK_IN_CUSTOMER):
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": WALK_IN_CUSTOMER,
				"customer_type": "Individual",
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
				"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
			}
		).insert(ignore_permissions=True)
	return WALK_IN_CUSTOMER


def cash_method(company: str) -> str:
	"""Cash, with an account for this company, so a till's invoice can settle."""
	if not frappe.db.exists("Mode of Payment", "Cash"):
		method = frappe.get_doc({"doctype": "Mode of Payment", "mode_of_payment": "Cash", "type": "Cash"})
		fill_zatca_means(method, ZATCA_MEANS_CASH)
		method.insert(ignore_permissions=True)

	method = frappe.get_doc("Mode of Payment", "Cash")
	if not any(row.company == company for row in method.accounts):
		account = frappe.db.get_value(
			"Account", {"company": company, "account_type": "Cash", "is_group": 0}, "name"
		) or frappe.db.get_value(
			"Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name"
		)
		if account:
			method.append("accounts", {"company": company, "default_account": account})
			fill_zatca_means(method, ZATCA_MEANS_CASH)
			method.save(ignore_permissions=True)

	return "Cash"


def _branch(name: str, company: str) -> str:
	basics = company_basics(company)
	frappe.get_doc(
		{
			"doctype": "Branch",
			"branch": name,
			"company": company,
			"default_warehouse": basics.warehouse,
			"default_cost_center": basics.cost_center,
		}
	).insert()
	return name


def _section(branch: str, kind: str) -> str:
	_kind, title, title_ar = next(row for row in SECTIONS if row[0] == kind)
	return (
		frappe.get_doc(
			{
				"doctype": "Restaurant Section",
				"title": title,
				"title_ar": title_ar,
				"branch": branch,
				"section_type": kind,
				"is_active": 1,
			}
		)
		.insert()
		.name
	)


def _tables(section: str, count: int) -> None:
	for number in range(1, count + 1):
		frappe.get_doc(
			{
				"doctype": "Restaurant Table",
				"table_number": str(number),
				"section": section,
				"capacity": 4,
				"status": "available",
				"is_active": 1,
			}
		).insert()


def _terminal(name: str, company: str, section: str, price_list: str | None, taxes: str | None) -> str:
	basics = company_basics(company)
	taxes = taxes or frappe.db.get_value(
		"Sales Taxes and Charges Template", {"company": company, "is_default": 1, "disabled": 0}, "name"
	)
	profile = frappe.get_doc(
		{
			"doctype": "POS Profile",
			"name": name,
			"company": company,
			"currency": frappe.db.get_value("Company", company, "default_currency"),
			"warehouse": basics.warehouse,
			"write_off_account": basics.write_off,
			"write_off_cost_center": basics.cost_center,
			"write_off_limit": 1,
			"customer": walk_in_customer(),
			"restaurant_section": section,
			"selling_price_list": price_list
			or frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name"),
			"taxes_and_charges": taxes,
			"payments": [{"mode_of_payment": cash_method(company), "default": 1}],
		}
	)
	profile.insert()
	return profile.name

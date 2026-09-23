# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The three accounts a drawer's cash movements land in, and the reasons they serve.

**Why ready-made** (`D-246`). The user was asked which accounts to post a pay-out
to and answered honestly that they had no idea — which is the normal answer from
somebody running a restaurant rather than a ledger. Toast solves it by letting
the manager map each pay-out reason to a GL account; the mapping is right, but a
manager who does not know their chart of accounts cannot make it from nothing.

So three accounts are created under the groups ERPNext's own chart already ships,
and the four shipped reasons are pointed at them. They are named, not hidden, and
a restaurant with an accountant renames them or points the reasons elsewhere.

**Never overwritten.** An account that exists is left alone and a reason that
already names an account keeps it, so a manager's choice survives every migrate.

Refs: D-245, D-246
"""

import frappe

#: What each account is for, and where ERPNext's standard chart puts that kind.
#:
#: The safe is cash, not an expense: change fetched from it and takings carried
#: to it move money between two boxes the restaurant owns. A driver's float is
#: an advance they still owe back, which is why it sits under Loans and
#: Advances rather than being written off the moment it leaves the till.
ACCOUNTS = (
	{
		"key": "safe",
		"account_name": "خزنة المطعم",
		"parent": "Cash In Hand",
		"root_type": "Asset",
		"account_type": "Cash",
	},
	{
		"key": "running_costs",
		"account_name": "مصروفات تشغيل المطعم",
		"parent": "Indirect Expenses",
		"root_type": "Expense",
		"account_type": "Expense Account",
	},
	{
		"key": "staff_advances",
		"account_name": "عهد الموظفين",
		"parent": "Loans and Advances (Assets)",
		"root_type": "Asset",
		"account_type": "",
	},
)

#: Which shipped reason posts to which of them, by the reason's English title.
REASON_ACCOUNTS = {
	"Change from the safe": "safe",
	"Cash to the safe": "safe",
	"Bought supplies": "running_costs",
	"Delivery driver float": "staff_advances",
}


def setup(company: str | None = None) -> dict[str, str]:
	"""Create the accounts if they are missing and point the reasons at them."""
	company = company or frappe.defaults.get_global_default("company")
	if not company:
		return {}

	created = {spec["key"]: _ensure_account(spec, company) for spec in ACCOUNTS}
	_point_reasons_at(created)
	return created


def _ensure_account(spec: dict, company: str) -> str | None:
	"""The account, made under its standard parent — or whatever is already there."""
	abbr = frappe.db.get_value("Company", company, "abbr")
	name = f"{spec['account_name']} - {abbr}"
	if frappe.db.exists("Account", name):
		return name

	parent = frappe.db.get_value(
		"Account", {"company": company, "account_name": spec["parent"], "is_group": 1}, "name"
	)
	if not parent:
		# A chart that does not carry ERPNext's standard groups is one somebody
		# built deliberately; guessing a parent in it would be worse than not
		# creating the account at all.
		return None

	account = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": spec["account_name"],
			"parent_account": parent,
			"company": company,
			"root_type": spec["root_type"],
			"account_type": spec["account_type"] or None,
			"is_group": 0,
		}
	).insert(ignore_permissions=True)

	return account.name


def _point_reasons_at(accounts: dict[str, str | None]) -> None:
	"""Give each shipped reason its account, unless it already names one."""
	for title, key in REASON_ACCOUNTS.items():
		account = accounts.get(key)
		if not account or not frappe.db.exists("POS Quick Note", title):
			continue

		if frappe.db.get_value("POS Quick Note", title, "expense_account"):
			continue

		frappe.db.set_value("POS Quick Note", title, "expense_account", account, update_modified=False)

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Where a gift card's money sits until somebody eats it (`D-256`).

**A card sold is not a sale.** The restaurant has taken cash and given nothing
but a promise, so the money is a **liability** until the guest comes back — the
treatment every accounting standard and every till in this trade uses.

**And in Saudi Arabia no VAT is due when the card is sold.** Article 19 of the
VAT Implementing Regulations treats a face-value voucher sold at its face value
as no supply at all; the tax falls when the card is redeemed, on the food. So a
card sale never becomes a `Sales Invoice` here — it is a journal entry, cash in
against the liability. (Europe's single-purpose voucher rule taxes at issue,
which is why copying an English-language guide would have been wrong.)

**The clever half is the payment mode.** The mode a cashier picks to spend a
card points at **the same liability account**, so redeeming settles an ordinary
invoice: ERPNext debits the liability and credits revenue, VAT and all, with no
arithmetic of ours in the ledger. The account's balance is then the outstanding
gift-card liability, and it reconciles against the sum of the card balances
without anybody keeping a second set of books.

**Never overwritten**, like the drawer's accounts (`D-246`): an account that
exists is left alone, and a mode already pointing somewhere keeps its account.

Refs: FR-11.5, D-246, D-256
"""

import frappe

#: The liability. Under Current Liabilities, where ERPNext's standard chart puts
#: money owed within the year — which is what an unspent card is.
ACCOUNT = {
	"account_name": "بطاقات هدايا غير مستخدمة",
	"parent": "Current Liabilities",
	"root_type": "Liability",
	"account_type": "",
}

#: What the cashier taps to spend a card. Not a till method: the money came in
#: when the card was sold, so counting it again at the close would show a drawer
#: holding cash that nobody ever put there (`D-029`).
MODE_OF_PAYMENT = "بطاقة هدايا"


def setup(company: str | None = None) -> dict[str, str | None]:
	"""Create the account and the payment mode if they are missing."""
	company = company or frappe.defaults.get_global_default("company") or _the_only_company()
	if not company:
		return {}

	account = _ensure_account(company)
	mode = _ensure_mode(company, account)
	return {"account": account, "mode_of_payment": mode}


def _the_only_company() -> str | None:
	"""The company, when a site has exactly one.

	**A global default is not always set** — the test site has none, and neither
	does a site somebody set up without touching Global Defaults. One company is
	not a guess; two would be, and then this returns nothing rather than picking
	the wrong ledger to owe money in.
	"""
	companies = frappe.get_all("Company", pluck="name", limit=2)
	return companies[0] if len(companies) == 1 else None


def _ensure_account(company: str) -> str | None:
	abbr = frappe.db.get_value("Company", company, "abbr")
	name = f"{ACCOUNT['account_name']} - {abbr}"
	if frappe.db.exists("Account", name):
		return name

	parent = frappe.db.get_value(
		"Account", {"company": company, "account_name": ACCOUNT["parent"], "is_group": 1}, "name"
	)
	if not parent:
		# A chart without ERPNext's standard groups was built by somebody on
		# purpose; guessing a parent inside it is worse than creating nothing.
		return None

	return (
		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": ACCOUNT["account_name"],
				"parent_account": parent,
				"company": company,
				"root_type": ACCOUNT["root_type"],
				"is_group": 0,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_mode(company: str, account: str | None) -> str | None:
	"""The payment mode, pointed at the liability account for this company."""
	if not frappe.db.exists("Mode of Payment", MODE_OF_PAYMENT):
		frappe.get_doc(
			{
				"doctype": "Mode of Payment",
				"mode_of_payment": MODE_OF_PAYMENT,
				"enabled": 1,
				"type": "General",
				# **Not a till method** (`D-029`). The cash came in when the card
				# was sold and was counted then; expecting it again at the close
				# would show every drawer holding money nobody ever put there.
				"rpos_is_credit": 1,
			}
		).insert(ignore_permissions=True)

	if not account:
		return MODE_OF_PAYMENT

	mode = frappe.get_doc("Mode of Payment", MODE_OF_PAYMENT)
	if any(row.company == company for row in mode.accounts):
		return MODE_OF_PAYMENT

	mode.append("accounts", {"company": company, "default_account": account})
	mode.save(ignore_permissions=True)
	return MODE_OF_PAYMENT

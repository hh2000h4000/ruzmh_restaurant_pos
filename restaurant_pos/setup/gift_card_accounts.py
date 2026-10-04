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

from restaurant_pos.setup.defaults import ZATCA_MEANS_UNDEFINED, fill_zatca_means
from restaurant_pos.utils.company import site_company

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
	company = site_company(company)
	if not company:
		return {}

	account = _ensure_account(company)
	try:
		mode = _ensure_mode(company, account)
	except frappe.MandatoryError as error:
		# **Another app's required field, whose value is not ours to invent.**
		# `ksa_compliance` makes a ZATCA payment-means code mandatory on every
		# payment mode, and which code a gift card carries is a tax answer. This
		# ran inside `after_migrate`, so the refusal stopped every step after it
		# on the user's site, migrate after migrate, with nobody told (`D-262`).
		# Said in the Error Log instead; the manager creates the mode by hand
		# with its code and ticks «Gift Card», and the next migrate links the
		# account to it. No
		# rollback: the insert is refused in validation, before it writes, and
		# a rollback here would undo everything `after_migrate` did before it.
		frappe.log_error(
			title=f"Payment mode «{MODE_OF_PAYMENT}» was not created",
			message=f"{error}\n\nCreate a Mode of Payment with that field filled and tick "
			"«Gift Card» on it — any name will do; the next migrate links the gift card "
			"account to it.",
		)
		mode = None
	return {"account": account, "mode_of_payment": mode}


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
	"""The gift card payment mode, pointed at the liability account for this company.

	**Found by its tick, not by its name** (`D-264`). A site whose manager made
	their own — in their words, in their language — keeps theirs once it is
	ticked. Only when nothing is ticked does the name come in: a mode already
	called «بطاقة هدايا» (every site set up before the tick existed) is ticked,
	and a site with neither gets one.
	"""
	name = frappe.db.get_value("Mode of Payment", {"rpos_is_gift_card": 1}, "name")
	if not name and frappe.db.exists("Mode of Payment", MODE_OF_PAYMENT):
		name = MODE_OF_PAYMENT
		frappe.db.set_value("Mode of Payment", name, "rpos_is_gift_card", 1)
	if not name:
		mode = frappe.get_doc(
			{
				"doctype": "Mode of Payment",
				"mode_of_payment": MODE_OF_PAYMENT,
				"enabled": 1,
				"type": "General",
				"rpos_is_gift_card": 1,
			}
		)
		fill_zatca_means(mode, ZATCA_MEANS_UNDEFINED)
		name = mode.insert(ignore_permissions=True).name

	# **Not credit, and this is enforced rather than left to whoever edited it**
	# (`D-257`). `rpos_is_credit` means *the money is still owed* — a delivery
	# platform, a company account — and it makes the invoice `is_pos = 0` with no
	# payment rows at all. Marked credit, a card-paid bill never touched the
	# liability account and left a receivable against a guest who owed nothing.
	# A card **is** settled; it simply settles from a balance instead of from the
	# drawer, and the drawer's own exclusion is `kind` in `utils/shift`.
	if frappe.db.get_value("Mode of Payment", name, "rpos_is_credit"):
		frappe.db.set_value("Mode of Payment", name, "rpos_is_credit", 0)

	if not account:
		return name

	mode = frappe.get_doc("Mode of Payment", name)
	if any(row.company == company for row in mode.accounts):
		return name

	mode.append("accounts", {"company": company, "default_account": account})
	# A method made before the ZATCA app was installed has no code, and saving it
	# would be refused for the field that app made mandatory (`D-306`).
	fill_zatca_means(mode, ZATCA_MEANS_UNDEFINED)
	mode.save(ignore_permissions=True)
	return name

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Book a drawer's difference, as the accountant decides (`D-357`).

The cashier reports it — the count and the reason, on the closing (`BR-043`) —
and the drawer variances report lays it out. What was missing is the last step:
the accountant had to open a blank journal entry, find the cash account and type
the figure, and nothing said which differences were already done.

So one closing, one entry, against the account the accountant picks: the
shortage account to write it off, or a receivable to charge the cashier, in
which case the cashier's employee record is the party. The entry is linked on
the closing, and a closing already booked is refused — the same difference
twice is money the books lose twice.
"""

import frappe
from frappe import _
from frappe.utils import flt

FIELD = "rpos_difference_entry"
SETTINGS = "Restaurant POS Settings"


def default_account() -> str | None:
	return frappe.db.get_single_value(SETTINGS, "over_short_account")


def booked(closing) -> str | None:
	"""The submitted entry already holding this closing's difference, if any."""
	entry = closing.get(FIELD)
	if entry and frappe.db.get_value("Journal Entry", entry, "docstatus") == 1:
		return entry
	return None


def book(closing_entry: str, account: str | None = None) -> str:
	"""Write this closing's difference to ``account``; return the journal entry."""
	closing = frappe.get_doc("POS Closing Entry", closing_entry)
	if closing.docstatus != 1:
		frappe.throw(_("Drawer {0} has not been closed.").format(closing.name))

	already = booked(closing)
	if already:
		frappe.throw(
			_("The difference on drawer {0} is already booked in {1}.").format(closing.name, already)
		)

	account = account or default_account()
	if not account:
		frappe.throw(_("Choose the account the difference goes to."))
	target = frappe.db.get_value("Account", account, ["company", "is_group", "account_type"], as_dict=True)
	if not target or target.company != closing.company or target.is_group:
		frappe.throw(
			_("{0} is not an account of {1} that entries can be made in.").format(account, closing.company)
		)

	party = _party_for(closing.user) if target.account_type in ("Receivable", "Payable") else {}

	rows = []
	for line in closing.payment_reconciliation:
		difference = flt(line.difference, 2)
		if not difference:
			continue
		drawer = frappe.db.get_value(
			"Mode of Payment Account",
			{"parent": line.mode_of_payment, "company": closing.company},
			"default_account",
		)
		if not drawer:
			frappe.throw(
				_("Payment method {0} has no account for {1}.").format(line.mode_of_payment, closing.company)
			)

		# Counted less expected: below zero is money missing — out of the
		# drawer's account, into the one the accountant chose.
		short, over = max(-difference, 0), max(difference, 0)
		rows.append(
			{"account": drawer, "debit_in_account_currency": over, "credit_in_account_currency": short}
		)
		rows.append(
			{"account": account, "debit_in_account_currency": short, "credit_in_account_currency": over}
			| party
		)

	if not rows:
		frappe.throw(_("Drawer {0} counted out as expected; there is nothing to book.").format(closing.name))

	entry = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": closing.company,
			"posting_date": closing.posting_date,
			"user_remark": _("Difference on drawer {0} ({1}), closed by {2}.").format(
				closing.name, closing.pos_profile, closing.user
			),
			"accounts": rows,
		}
	)
	entry.insert()
	entry.submit()

	frappe.db.set_value("POS Closing Entry", closing.name, FIELD, entry.name, update_modified=False)
	return entry.name


def release(entry, method=None) -> None:
	"""``Journal Entry.before_cancel`` — the closing forgets an entry being cancelled.

	Otherwise Frappe refuses the cancel because the closing links to it, and an
	accountant who booked to the wrong account could never put it right.
	"""
	closing = frappe.db.get_value("POS Closing Entry", {FIELD: entry.name}, "name")
	if closing:
		frappe.db.set_value("POS Closing Entry", closing, FIELD, None, update_modified=False)


def _party_for(user: str) -> dict:
	"""The cashier as a party, for charging them the difference."""
	employee = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
	if not employee:
		frappe.throw(
			_("{0} has no employee record, so the difference cannot be charged to them.").format(
				frappe.db.get_value("User", user, "full_name") or user
			)
		)
	return {"party_type": "Employee", "party": employee}

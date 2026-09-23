# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Money in or out of an open drawer, for something that is not a sale.

**The gap this closes.** A cashier sends somebody for a bag of ice, or takes a
float of change from the safe, and the notes move. Nothing recorded it, so the
count at closing came up short or long by exactly that amount — and a drawer
that disagrees with its expected figure for a reason nobody wrote down is a
shortage pinned on whoever was holding it (`D-245`).

Every register on the market has this; the classic ones print it on the tape as
PAID IN and PAID OUT.

**It lands in the drawer it left**, not in the day: `summarise_till` adds it to
what the drawer is expected to hold, so the count and the expectation agree
again. And it is written through `assert_may_sell`, the same gate a sale passes
(`D-058`) — a drawer that has been counted and handed over cannot have money
taken out of it afterwards.

**And it reaches the ledger through its reason** (`D-246`). Toast maps each
pay-out reason to a GL account, and so does this: the manager chooses the
account once, on the reason, and the cashier taps a chip. A movement then posts
its own `Cash Entry` — the reason's account against the drawer's cash account,
which ERPNext already knows from `Mode of Payment Account`.

**The books never hold the drawer hostage.** A reason with no account, a payment
method with no account, a closed accounting period — none of them stop the
movement being recorded, because the count at closing has to be right either
way. What did not post is written on the movement in words, so it is a job
somebody can finish rather than a silence.

Refs: FR-8.3, BR-041, BR-044, D-058, D-245, D-246
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, now_datetime

from restaurant_pos.utils.audit import log_audit
from restaurant_pos.utils.order import table_section_branch
from restaurant_pos.utils.permissions import (
	consume_override_token,
	get_pos_permission_set,
	validate_branch_access,
)

#: The permission a cashier needs to move money in or out on their own — and the
#: action a manager's PIN is asked for when they do not have it. The two are one
#: string on purpose: `find_approver_for_pin` checks the approver holds exactly
#: the permission being borrowed, as every other override here does.
PERMISSION = "can_move_drawer_cash"

DIRECTIONS = ("in", "out")


def record(
	pos_profile: str,
	*,
	direction: str,
	amount: float,
	reason: str,
	mode_of_payment: str | None = None,
	override_token: str | None = None,
) -> dict:
	"""Write one movement against the drawer this terminal is selling into."""
	if direction not in DIRECTIONS:
		frappe.throw(_("A cash movement is either in or out."))

	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("A cash movement must be more than zero."))

	if not (reason or "").strip():
		frappe.throw(_("Say what the money was for."))

	# Imported here, not at the top: `shift` reads `totals_of` below to work out
	# what a drawer should hold, and importing it back at module level makes the
	# pair circular. The read half of this module has no dependency at all.
	from restaurant_pos.utils.shift import assert_may_sell, selling_till

	# The drawer gate before the permission one: there is nothing to authorise
	# when there is no open drawer to move money out of.
	assert_may_sell(pos_profile)

	# A terminal carries no branch of its own; it hangs off its section, and this
	# is the resolver the shift module already uses.
	section = frappe.db.get_value("POS Profile", pos_profile, "restaurant_section")
	branch = table_section_branch(section)

	# **Somebody else's branch is not yours to take notes out of.** The shift gate
	# above asks whether that terminal may sell, not whether this cashier belongs
	# to it — `test_api_surface` found the difference before a user could.
	validate_branch_access(branch)

	till = selling_till(pos_profile)
	approved_by = _authorise(override_token)

	movement = frappe.get_doc(
		{
			"doctype": "POS Cash Movement",
			"pos_opening_entry": till.name,
			"pos_profile": pos_profile,
			"branch": branch,
			"direction": direction,
			"amount": amount,
			"mode_of_payment": mode_of_payment or _cash_method(pos_profile),
			"reason": reason.strip(),
			"moved_at": now_datetime(),
			"cashier": frappe.session.user,
			"approved_by": approved_by,
		}
	).insert(ignore_permissions=True)

	_post_to_ledger(movement, pos_profile)

	log_audit(
		f"cash_{direction}",
		branch=branch,
		pos_profile=pos_profile,
		approved_by=approved_by,
		reason=movement.reason,
		details={
			"movement": movement.name,
			"drawer": till.name,
			"amount": amount,
			"mode_of_payment": movement.mode_of_payment,
		},
	)

	return {
		"movement": movement.name,
		"drawer": till.name,
		"amount": amount,
		"direction": direction,
		"journal_entry": movement.journal_entry,
	}


def _post_to_ledger(movement, pos_profile: str) -> None:
	"""One `Cash Entry`: the reason's account against the drawer's cash account.

	Written onto the movement either way — the voucher when it posted, and the
	sentence saying why not when it did not.
	"""
	account = frappe.db.get_value("POS Quick Note", {"title_ar": movement.reason}, "expense_account")
	if not account:
		account = frappe.db.get_value("POS Quick Note", {"title": movement.reason}, "expense_account")

	if not account:
		return _not_posted(movement, _("This reason has no accounting account."))

	terminal = frappe.db.get_value("POS Profile", pos_profile, ["company", "cost_center"], as_dict=True)
	cash_account = frappe.db.get_value(
		"Mode of Payment Account",
		{"parent": movement.mode_of_payment, "company": terminal.company},
		"default_account",
	)
	if not cash_account:
		return _not_posted(
			movement, _("{0} has no account on this company.").format(movement.mode_of_payment)
		)

	# Out of the drawer: the reason's account takes it and the cash account gives
	# it up. In: the other way round.
	debit, credit = (account, cash_account) if movement.direction == "out" else (cash_account, account)
	cost_center = terminal.cost_center or frappe.db.get_value("Company", terminal.company, "cost_center")

	try:
		entry = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"voucher_type": "Cash Entry",
				"company": terminal.company,
				"posting_date": getdate(movement.moved_at),
				"user_remark": f"{movement.reason} ({movement.name})",
				"accounts": [
					{
						"account": debit,
						"debit_in_account_currency": flt(movement.amount),
						"cost_center": cost_center,
					},
					{
						"account": credit,
						"credit_in_account_currency": flt(movement.amount),
						"cost_center": cost_center,
					},
				],
			}
		).insert(ignore_permissions=True)
		entry.submit()
	except Exception as refusal:
		# A closed period, a frozen account, a chart somebody rearranged. The
		# drawer is already right; this is the books saying not yet.
		frappe.db.set_value(
			"POS Cash Movement", movement.name, "posting_note", str(refusal), update_modified=False
		)
		return

	frappe.db.set_value(
		"POS Cash Movement", movement.name, "journal_entry", entry.name, update_modified=False
	)
	movement.journal_entry = entry.name


def _not_posted(movement, why: str) -> None:
	frappe.db.set_value("POS Cash Movement", movement.name, "posting_note", why, update_modified=False)


def _authorise(override_token: str | None) -> str | None:
	"""Who allowed it — nobody, when the cashier holds the permission themselves.

	Taking notes out of a till is what a manager's PIN is for, so a cashier
	without the permission is not refused outright: they are asked, the way a
	discount over their ceiling asks (`D-147`).
	"""
	if get_pos_permission_set().get(PERMISSION):
		return None

	if not override_token:
		frappe.throw(
			_("Moving money in or out of the drawer needs a manager."),
			frappe.PermissionError,
		)

	return consume_override_token(override_token, PERMISSION)


def _cash_method(pos_profile: str) -> str:
	"""The drawer's own cash line — the one a movement changes.

	Read from the terminal's payment methods rather than named here, because a
	branch calls it what it likes and the expected figure is tallied per method.
	"""
	for row in frappe.get_all(
		"POS Payment Method",
		filters={"parent": pos_profile, "parenttype": "POS Profile"},
		fields=["mode_of_payment", "default"],
		order_by="`default` desc, idx asc",
	):
		if not frappe.db.get_value("Mode of Payment", row.mode_of_payment, "rpos_is_credit"):
			return row.mode_of_payment

	frappe.throw(_("POS Profile {0} has no cash payment method.").format(pos_profile))


def totals_of(opening_entry: str) -> dict[str, dict[str, float]]:
	"""What each payment method gained and lost outside of selling.

	Keyed by method so `summarise_till` can add it to the right line: a drawer
	holds its methods apart, and money taken out of the cash box is not money
	taken off the card machine.
	"""
	tally: dict[str, dict[str, float]] = {}

	for row in frappe.get_all(
		"POS Cash Movement",
		filters={"pos_opening_entry": opening_entry},
		fields=["mode_of_payment", "direction", "amount"],
	):
		line = tally.setdefault(row.mode_of_payment, {"in": 0.0, "out": 0.0})
		line[row.direction] += flt(row.amount)

	return tally

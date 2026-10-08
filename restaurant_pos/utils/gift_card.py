# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Money the guest has already handed over (`D-256`).

**A gift card is not a discount, and that difference is the whole design.** A
coupon takes something off the price (`D-248`); a card pays it. So the bill is
charged in full, VAT is charged on all of it, and the card settles the total the
way cash does. Treating a card as a discount would hand the tax authority less
tax than the restaurant actually collected.

**Selling a card is not a sale.** The restaurant has taken money and given back
a promise, so the cash goes in against a **liability** — and in Saudi Arabia
**no VAT is due at that moment**: Article 19 of the VAT Implementing Regulations
treats a face-value voucher sold at its face value as no supply at all, and the
tax falls when the card is spent, on the food. That is why a card sale never
becomes a `Sales Invoice` here, only a journal entry. (Europe taxes a
single-purpose voucher at issue, which is why following an English-language
guide would have been wrong here.)

**Spending one needs no arithmetic in the ledger.** The payment mode points at
the same liability account (`setup/gift_card_accounts`), so an ordinary invoice
settled with it debits the liability and credits revenue and VAT by itself. The
account's balance is then the outstanding gift-card liability, and it reconciles
against the sum of the cards without a second set of books.

**The entries are the record.** `POS Gift Card.balance` is kept in step with
them so a till need not add up at the counter, but every figure an accountant is
asked to trust is a sum of `POS Gift Card Entry` rows.

Refs: FR-11.5, D-029, D-246, D-256
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate, now_datetime, nowdate

from restaurant_pos.utils import codes
from restaurant_pos.utils.audit import log_audit
from restaurant_pos.utils.company import site_company
from restaurant_pos.utils.order import table_section_branch
from restaurant_pos.utils.permissions import assert_permission, validate_branch_access
from restaurant_pos.utils.totals import money

#: What one card may be loaded with. A ceiling exists because a mistyped amount
#: is a liability on the books and an argument at the counter.
MAX_LOAD = 10000.0

#: What the entries do to a balance.
ADDS = ("issue", "top_up", "refund")
TAKES = ("redeem", "void")


def is_gift_card_method(method: str | None) -> bool:
	"""Whether this payment method spends a gift card's balance (`D-264`).

	**The field, never the name.** The name is whatever the manager typed, in
	whatever language — and the one this code used to compare against was
	misspelt on the first site that made its own: «بطاقة هدية» for «بطاقة
	هدايا», and the till would have taken it like cash and asked for no card.
	"""
	return bool(method) and bool(frappe.db.get_value("Mode of Payment", method, "rpos_is_gift_card"))


def gift_card_method() -> str | None:
	"""The method marked as the gift card — one per site (`D-264`).

	One, because its account **is** the liability every card is owed from, and
	two methods could name two accounts for the same promise.
	"""
	return frappe.db.get_value("Mode of Payment", {"rpos_is_gift_card": 1}, "name")


def validate_mode_of_payment(doc, method=None) -> None:
	"""Keep the gift card tick meaning one thing (`D-264`, `D-257`).

	**Not credit as well.** Credit makes the invoice `is_pos = 0` with no payment
	rows, so a card-paid bill would never reach the liability account.

	**Not on two methods.** Every card is owed from the one method's account;
	a second tick could point half the cards at a different account.
	"""
	if not doc.get("rpos_is_gift_card"):
		return

	if doc.get("rpos_is_credit"):
		frappe.throw(_("A gift card method is paid from the card's balance, not settled on account."))

	other = frappe.db.get_value("Mode of Payment", {"rpos_is_gift_card": 1, "name": ("!=", doc.name)}, "name")
	if other:
		frappe.throw(_("{0} is already the gift card method. Only one can be.").format(other))

	# **Its account is what the restaurant owes** (`D-265`). ERPNext's form
	# offered only cash, bank and receivable accounts, so the first manager to
	# set this up made a new one under Cash In Hand — and every card spent from
	# it read as cash in the box while the debt to the guests never appeared.
	for row in doc.get("accounts") or []:
		if (
			row.default_account
			and frappe.db.get_value("Account", row.default_account, "root_type") != "Liability"
		):
			frappe.throw(
				_(
					"{0} is not a liability. A gift card method's account is what the restaurant owes the card's holder."
				).format(row.default_account)
			)


def _liability(company: str) -> str | None:
	"""The account every card on this company is owed from."""
	method = gift_card_method()
	if not method:
		return None
	return frappe.db.get_value(
		"Mode of Payment Account", {"parent": method, "company": company}, "default_account"
	)


def vat_falls_at() -> str:
	"""When the tax on a gift card becomes due — **the one country-dependent rule**.

	Named as a function with nothing to decide yet, on purpose. It is the single
	place the answer lives, so a restaurant group opening outside Saudi Arabia
	changes one seam instead of hunting through the ledger, the payment path and
	the print templates for assumptions nobody wrote down.

	**Saudi Arabia — `"redemption"`, which is what this returns.** Article 19 of
	the VAT Implementing Regulations treats a face-value voucher sold at its face
	value as no supply at all: the card sale raises no invoice and no VAT, and
	the tax falls when the card is spent, on the food.

	**The other regime is `"issue"`**, which the EU and the UK apply to a
	*single-purpose* voucher — one where the rate and the place of supply are
	already known when it is sold. There the card sale **is** a taxable supply
	and the redemption is not, so it would need:

	* the sale to raise a tax invoice rather than the journal entry below, and
	* **the meal's invoice to post with no VAT when a card settles it** — the
	  half that makes this more than a flag, because a bill paid half by card and
	  half in cash then carries tax on one half of the same dishes.

	Note also that a restaurant whose menu carries more than one VAT rate issues
	a *multi-purpose* voucher even in Europe, and is taxed on redemption exactly
	as here. The branch below is for a single-rate menu abroad, and is not built:
	a switch with one honest setting and one that lies is worse than no switch
	(`CLAUDE.md` §5.5). It is built the day a second country is real, and this
	docstring is the specification for that day.
	"""
	return "redemption"


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #


def find(card_number: str):
	"""The card, or a sentence saying exactly why it cannot be used.

	Each refusal is its own message, for the reason the coupon refusals are
	(`D-248`): *no such card*, *switched off*, *expired* and *empty* are four
	different things to do about it, and one word for all four tells the cashier
	nothing they can act on.
	"""
	number = (card_number or "").strip().upper()
	if not number:
		frappe.throw(_("Enter the gift card number."))

	name = frappe.db.get_value("POS Gift Card", {"card_number": number}, "name")
	if not name:
		frappe.throw(_("No gift card with that number."))

	card = frappe.get_doc("POS Gift Card", name)

	if not card.is_active:
		frappe.throw(_("This gift card is switched off."))

	if card.expires_on and getdate(card.expires_on) < getdate(nowdate()):
		frappe.throw(_("This gift card expired on {0}.").format(card.expires_on))

	return card


def balance_of(card_number: str) -> float:
	"""What is left on a card, read from its entries."""
	card = frappe.db.get_value("POS Gift Card", {"card_number": (card_number or "").strip().upper()})
	return _ledger_balance(card) if card else 0.0


def _ledger_balance(card: str) -> float:
	rows = frappe.get_all("POS Gift Card Entry", filters={"gift_card": card}, fields=["entry_type", "amount"])
	added = sum(flt(row.amount) for row in rows if row.entry_type in ADDS)
	spent = sum(flt(row.amount) for row in rows if row.entry_type in TAKES)
	return money(added - spent)


# --------------------------------------------------------------------------- #
# Selling one
# --------------------------------------------------------------------------- #


def issue(
	pos_profile: str,
	*,
	card_number: str,
	amount: float,
	mode_of_payment: str,
	customer: str | None = None,
	expires_on: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Sell a card: take the money, raise the liability, hand over the number."""
	amount = flt(amount)
	if amount <= 0 or amount > MAX_LOAD:
		frappe.throw(_("A gift card is loaded with between 0.01 and {0}.").format(f"{money(MAX_LOAD):.2f}"))

	number = (card_number or "").strip().upper()
	if not number:
		frappe.throw(_("Enter the gift card number."))

	# Imported here rather than at the top: `shift` reads this module to work out
	# what a drawer should hold, and importing it back makes the pair circular —
	# the same knot `cash_movement` unties the same way.
	from restaurant_pos.utils.shift import assert_may_sell, selling_till

	assert_may_sell(pos_profile)

	section = frappe.db.get_value("POS Profile", pos_profile, "restaurant_section")
	branch = table_section_branch(section)
	validate_branch_access(branch)
	assert_permission("can_sell_gift_card")

	done = _already_done(queue_id)
	if done:
		return done

	if frappe.db.exists("POS Gift Card", {"card_number": number}):
		frappe.throw(_("Gift card {0} exists already.").format(number))

	till = selling_till(pos_profile)
	accounts = _sale_accounts(pos_profile, mode_of_payment)

	card = frappe.get_doc(
		{
			"doctype": "POS Gift Card",
			"card_number": number,
			"customer": customer,
			"is_active": 1,
			"expires_on": expires_on,
			"initial_value": amount,
			"balance": amount,
			"issued_branch": branch,
			"issued_pos_profile": pos_profile,
			"issued_by": frappe.session.user,
			"issued_at": now_datetime(),
		}
	).insert(ignore_permissions=True)

	entry = _write_entry(
		card,
		entry_type="issue",
		amount=amount,
		branch=branch,
		pos_profile=pos_profile,
		queue_id=queue_id,
		mode_of_payment=mode_of_payment,
		pos_opening_entry=till.name,
	)

	voucher = _post_issue(card, amount, accounts)
	entry.db_set("journal_entry", voucher, update_modified=False)

	log_audit(
		"gift_card_issued",
		branch=branch,
		pos_profile=pos_profile,
		details={
			"gift_card": card.name,
			"amount": amount,
			"mode_of_payment": mode_of_payment,
			"drawer": till.name,
		},
	)

	return {
		"gift_card": card.name,
		"card_number": card.card_number,
		"amount": amount,
		"balance": money(amount),
		"journal_entry": voucher,
	}


def _post_issue(card, amount: float, accounts: tuple) -> str:
	"""Cash in, liability up — and **never a Sales Invoice** (Article 19).

	**No entry, no card** (`D-266`). This used to return None and write «not
	posted» on the card, the rule the drawer's cash movements follow (`D-246`).
	A card is not a cash movement: it carries a balance the till will pay out,
	so a card the books do not owe is money promised with no trace. The user's
	first two cards went out exactly so, before the method had an account. The
	refusal rolls back the whole request, the card with it.
	"""
	if vat_falls_at() != "redemption":
		# Unreachable while the seam has one answer, and left standing so the day
		# it gains a second one this fails loudly rather than posting a card sale
		# under the wrong regime.
		frappe.throw(_("Gift cards taxed at issue are not built yet."))

	terminal, liability, cash_account, cost_center = accounts

	try:
		entry = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"voucher_type": "Cash Entry",
				"company": terminal.company,
				"posting_date": getdate(now_datetime()),
				"user_remark": _("Gift card {0} sold").format(card.card_number),
				"accounts": [
					{
						"account": cash_account,
						"debit_in_account_currency": amount,
						"cost_center": cost_center,
					},
					{
						"account": liability,
						"credit_in_account_currency": amount,
						"cost_center": cost_center,
					},
				],
			}
		).insert(ignore_permissions=True)
		entry.submit()
		return entry.name
	except Exception:
		frappe.log_error(f"Gift card {card.name} did not post", "RPOS gift card")
		_refuse_unposted()


def _sale_accounts(pos_profile: str, mode_of_payment: str) -> tuple:
	"""Where a card sold at this till posts — asked **before** the card exists.

	So a refusal leaves nothing behind whether or not anything rolls it back.
	"""
	# **Only money that arrives pays for a card** (`D-276`). A card bought with
	# a card moved the liability onto itself and left a new balance nobody paid
	# for; a platform's or a company's credit line is money still owed, not
	# money in the drawer. The sell sheet listed both.
	if is_gift_card_method(mode_of_payment) or frappe.db.get_value(
		"Mode of Payment", mode_of_payment, "rpos_is_credit"
	):
		frappe.throw(
			_("{0} takes no money at the till, so it cannot pay for a gift card.").format(mode_of_payment)
		)

	terminal = frappe.db.get_value("POS Profile", pos_profile, ["company", "cost_center"], as_dict=True)

	liability = _liability(terminal.company)
	if not liability:
		_refuse_without_liability(terminal.company)

	cash_account = frappe.db.get_value(
		"Mode of Payment Account",
		{"parent": mode_of_payment, "company": terminal.company},
		"default_account",
	)
	if not cash_account:
		frappe.throw(
			_("{0} has no account on {1}, so the card's money has nowhere to go.").format(
				mode_of_payment, terminal.company
			)
		)

	cost_center = terminal.cost_center or frappe.db.get_value("Company", terminal.company, "cost_center")
	return terminal, liability, cash_account, cost_center


def issue_batch(
	*,
	count: int,
	amount: float,
	customer: str | None = None,
	account: str | None = None,
	pattern: str = "random",
	prefix: str | None = None,
	start: str | None = None,
	expires_on: str | None = None,
	company: str | None = None,
) -> dict:
	"""Issue cards from the office, where no drawer is involved (`D-260`).

	**The user asked the question that found this:** *"shouldn't a company order
	cards and have them settled from the back office rather than the till?"* Both
	happen — a walk-in buys one at the counter, and a company orders fifty and
	pays by transfer — and only the first was built. Worse, a card typed into the
	desk by hand showed a balance its ledger did not have and died at the till.

	**The money never touches a drawer**, which is the whole difference. The card
	sale at the till debits the cash the drawer took; this debits whatever the
	office says it came from — the bank, or the customer's own account, which is
	the usual case because the cards go out before the transfer lands. The entry
	carries the party, so the accountant settles it with a Payment Entry exactly
	as they settle an invoice.

	**And no `pos_opening_entry`**, so `takings_of` never counts these into a
	till's expected cash. That is by construction rather than by a rule somebody
	has to remember.
	"""
	frappe.has_permission("POS Gift Card", "create", throw=True)

	amount = flt(amount)
	if amount <= 0 or amount > MAX_LOAD:
		frappe.throw(_("A gift card is loaded with between 0.01 and {0}.").format(f"{money(MAX_LOAD):.2f}"))

	if not account and not customer:
		frappe.throw(_("Say where the money came from: a customer's account, or an account."))

	accounts = _office_accounts(customer, account, company)
	numbers = codes.make("POS Gift Card", count=count, pattern=pattern, prefix=prefix, start=start)

	made, entries = [], []
	for number in numbers:
		card = frappe.get_doc(
			{
				"doctype": "POS Gift Card",
				"card_number": number,
				"customer": customer,
				"is_active": 1,
				"expires_on": expires_on,
				"initial_value": amount,
				"issued_by": frappe.session.user,
				"issued_at": now_datetime(),
			}
		).insert(ignore_permissions=True)

		entries.append(
			_write_entry(
				card,
				entry_type="issue",
				amount=amount,
				branch=None,
				pos_profile=None,
				reason=_("Issued from the office"),
			)
		)
		made.append(card.name)

	voucher = _post_office_issue(made, amount * len(made), accounts)
	# Each card's row names the batch's voucher, as a till sale's row names its
	# own: it is how a row is known to have reached the books (`D-267`).
	for entry in entries:
		entry.db_set("journal_entry", voucher, update_modified=False)

	log_audit(
		"gift_card_issued",
		# **Empty on purpose.** This happened in an office, not at a till: there
		# is no terminal and no branch, and naming one would put the act somewhere
		# it did not occur.
		branch=None,
		pos_profile=None,
		details={
			"cards": made,
			"amount_each": amount,
			"customer": customer,
			"account": account,
			"journal_entry": voucher,
		},
	)

	return {"cards": made, "amount": amount, "journal_entry": voucher}


def _office_accounts(customer: str | None, account: str | None, company: str | None) -> tuple:
	"""What an office batch debits and credits — asked **before** any card exists.

	**Against the customer's account when no account is named**, with the party on
	the line — so a company that has not paid yet owes exactly this, and the
	transfer is matched against it later like any other receivable. Naming an
	account instead is the simple case: the money is already in the bank.
	"""
	company = site_company(company)
	if not company:
		frappe.throw(_("Which company? This site has more than one and none is the default."))

	liability = _liability(company)
	if not liability:
		_refuse_without_liability(company)

	cost_center = frappe.db.get_value("Company", company, "cost_center")
	debit = {"credit_in_account_currency": 0.0, "cost_center": cost_center}
	if account:
		debit["account"] = account
	else:
		debit["account"] = frappe.db.get_value("Company", company, "default_receivable_account")
		debit["party_type"] = "Customer"
		debit["party"] = customer

	if not debit["account"]:
		frappe.throw(
			_("{0} has no default receivable account, so the customer cannot owe for the cards.").format(
				company
			)
		)

	return company, liability, debit, cost_center


def _post_office_issue(cards: list[str], total: float, accounts: tuple) -> str:
	"""One voucher for the batch: what it came from, against the liability."""
	company, liability, debit, cost_center = accounts
	debit = {**debit, "debit_in_account_currency": total}

	try:
		entry = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"voucher_type": "Journal Entry",
				"company": company,
				"posting_date": getdate(now_datetime()),
				"user_remark": _("{0} gift cards issued").format(len(cards)),
				"accounts": [
					debit,
					{
						"account": liability,
						"credit_in_account_currency": total,
						"cost_center": cost_center,
					},
				],
			}
		).insert(ignore_permissions=True)
		entry.submit()
		return entry.name
	except Exception:
		frappe.log_error(f"Office gift cards {cards[:3]} did not post", "RPOS gift card")
		_refuse_unposted()


# --------------------------------------------------------------------------- #
# Cancelling one that was never spent
# --------------------------------------------------------------------------- #


def void(card_name: str, reason: str) -> dict:
	"""Cancel a card nobody has spent from — the books put back as they were (`D-267`).

	**What the professional systems do, and why this is not a delete.** Toast
	voids an unused card, Square refunds its purchase, and neither lets a card
	that ever reached the books disappear: the card stays, cancelled, with the
	entry that cancelled it. The user asked for both a delete and a cancel; the
	delete is kept for a record the books never saw (`POSGiftCard.on_trash`).

	**Reversed against where it came from, per issue.** Each issue has a journal
	entry; the reversal debits the liability and credits that entry's own source
	line — the till's cash, the bank, or the company's account with its party —
	for this card's amount. An office batch posts one entry for many cards, so
	cancelling one card cannot simply cancel that entry.

	**A card sold at the till goes back out of the drawer it came into**, so that
	drawer must still be open: the guest is handed the money, and `takings_of`
	takes the sale back out of what the count expects. Once the drawer has closed
	its money was counted and handed over, and nothing here can reach it.
	"""
	frappe.has_permission("POS Gift Card", "write", throw=True)

	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Say why the card is being cancelled."))

	card = frappe.get_doc("POS Gift Card", card_name)
	entries = frappe.get_all(
		"POS Gift Card Entry",
		filters={"gift_card": card.name},
		fields=[
			"entry_type",
			"amount",
			"journal_entry",
			"pos_opening_entry",
			"mode_of_payment",
			"branch",
			"pos_profile",
		],
		order_by="creation asc",
	)

	if any(row.entry_type == "void" for row in entries):
		frappe.throw(_("Gift card {0} is already cancelled.").format(card.card_number))
	if any(row.entry_type != "issue" for row in entries):
		frappe.throw(
			_("Gift card {0} has been spent from, so it cannot be cancelled. Switch it off instead.").format(
				card.card_number
			)
		)
	if not entries or any(not row.journal_entry for row in entries):
		frappe.throw(
			_(
				"Gift card {0} never reached the books, so there is nothing to reverse. Delete it instead."
			).format(card.card_number)
		)
	for row in entries:
		if (
			row.pos_opening_entry
			and frappe.db.get_value("POS Opening Entry", row.pos_opening_entry, "status") != "Open"
		):
			frappe.throw(
				_(
					"Gift card {0} was sold into a drawer that has closed, so its money cannot be "
					"handed back from it. Switch it off instead."
				).format(card.card_number)
			)

	reversals = []
	for row in entries:
		voucher = _reverse_issue(card, row, reason)
		entry = _write_entry(
			card,
			entry_type="void",
			amount=row.amount,
			branch=row.branch,
			pos_profile=row.pos_profile,
			reason=reason,
			mode_of_payment=row.mode_of_payment,
			pos_opening_entry=row.pos_opening_entry,
		)
		entry.db_set("journal_entry", voucher, update_modified=False)
		reversals.append(voucher)

	frappe.db.set_value("POS Gift Card", card.name, "is_active", 0)

	log_audit(
		"gift_card_voided",
		branch=entries[0].branch,
		pos_profile=entries[0].pos_profile,
		details={"gift_card": card.name, "reason": reason, "journal_entries": reversals},
	)

	return {"gift_card": card.name, "journal_entries": reversals}


def _reverse_issue(card, row, reason: str) -> str:
	"""The issue's own entry, backwards, for this card's amount."""
	issued = frappe.get_doc("Journal Entry", row.journal_entry)
	owed = next(line for line in issued.accounts if flt(line.credit_in_account_currency) > 0)
	source = next(line for line in issued.accounts if flt(line.debit_in_account_currency) > 0)
	amount = flt(row.amount)

	back = {
		"account": source.account,
		"credit_in_account_currency": amount,
		"cost_center": source.cost_center,
	}
	if source.party_type:
		back["party_type"] = source.party_type
		back["party"] = source.party

	entry = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": issued.voucher_type,
			"company": issued.company,
			"posting_date": getdate(now_datetime()),
			"user_remark": _("Gift card {0} cancelled: {1}").format(card.card_number, reason),
			"accounts": [
				{
					"account": owed.account,
					"debit_in_account_currency": amount,
					"cost_center": owed.cost_center,
				},
				back,
			],
		}
	).insert(ignore_permissions=True)
	entry.submit()
	return entry.name


def _refuse_without_liability(company: str) -> None:
	frappe.throw(
		_(
			"Gift cards cannot be issued yet: no payment method is marked «Gift Card» with a "
			"liability account for {0}. The guide's gift card page shows how to set it up."
		).format(company)
	)


def _refuse_unposted() -> None:
	frappe.throw(_("The card was not issued: its journal entry could not be posted. The Error Log says why."))


def takings_of(*opening_entries: str) -> dict[str, float]:
	"""What selling cards put into a drawer — or a day's drawers — per payment method (`D-256`).

	**A card sold is money in the box with no invoice behind it.** Every other
	figure the drawer expects comes from `Sales Invoice Payment`, and a card sale
	is deliberately not an invoice at all (Article 19, above) — so without this
	the cashier would count more cash than the screen ever asked for, every time
	somebody bought a card.

	Keyed by the method the *card* was paid with, not by the gift-card method: a
	card bought with a bank card put nothing in the cash box.
	"""
	tally: dict[str, float] = {}
	for row in frappe.get_all(
		"POS Gift Card Entry",
		filters={
			"pos_opening_entry": ("in", opening_entries),
			"entry_type": ("in", ("issue", "top_up", "void")),
		},
		fields=["mode_of_payment", "amount", "entry_type"],
	):
		if not row.mode_of_payment:
			continue
		# `D-267` — a cancelled sale handed its money back out of this drawer.
		sign = -1 if row.entry_type == "void" else 1
		tally[row.mode_of_payment] = tally.get(row.mode_of_payment, 0.0) + sign * flt(row.amount)

	return tally


# --------------------------------------------------------------------------- #
# Spending one
# --------------------------------------------------------------------------- #


def assert_spendable(payments: list[dict]) -> None:
	"""Check every card on this bill **before** the invoice exists.

	Refused here rather than after posting: an invoice submitted against a card
	that turns out to be empty is a sale with no money behind it, and undoing one
	is a credit note somebody has to explain.
	"""
	for row in card_rows(payments):
		card = find(row["gift_card"])
		balance = _ledger_balance(card.name)
		if flt(row["amount"]) > balance + 0.001:
			frappe.throw(
				_("Gift card {0} has {1} left.").format(card.card_number, f"{money(balance):.2f}"),
				frappe.ValidationError,
			)


def settle(order, invoice, payments: list[dict]) -> list[str]:
	"""Take the money off the cards, once the sale has actually posted.

	After the invoice, like the loyalty points and the coupon (`D-189`, `D-248`):
	a bill that failed to post spent nothing, and a card debited before it would
	be short by the price of a meal nobody ate.
	"""
	spent = []
	for row in card_rows(payments):
		card = frappe.get_doc("POS Gift Card", {"card_number": row["gift_card"]})
		entry = _write_entry(
			card,
			entry_type="redeem",
			amount=flt(row["amount"]),
			branch=order.branch,
			pos_profile=order.pos_profile,
			restaurant_order=order.name,
			sales_invoice=invoice.name,
		)
		spent.append(entry.name)

	return spent


def refund(credit) -> list[str]:
	"""Put a refunded amount back on the card it came off (`D-258`).

	**Back to the card, which is what every professional till does.** Square
	refunds to the original tender and Toast refuses anything else on a card
	payment, and the reason is a fraud path rather than neatness: cash handed
	back for a card-settled bill turns prepaid credit into notes — the way a card
	bought with a stolen payment card is emptied. `utils/returns` refuses that at
	the door; this is the other half, the money actually going home.

	**Which card is not guessed.** It is read from the redemption entries of the
	invoice being reversed, so a bill that spent two cards puts each amount back
	on the card it left. A refund larger than one card's share is refused before
	it reaches here.

	The ledger needs nothing from us: the credit note carries a payment row
	against the liability account, so the books raise the liability at the same
	moment these rows raise the balance.
	"""
	paid_back = [
		row
		for row in credit.get("payments") or []
		if is_gift_card_method(row.mode_of_payment) and flt(row.amount)
	]
	if not paid_back:
		return []

	spent = frappe.get_all(
		"POS Gift Card Entry",
		filters={"sales_invoice": credit.return_against, "entry_type": "redeem"},
		fields=["gift_card", "amount", "branch"],
		order_by="creation asc",
	)
	if not spent:
		return []

	left = sum(abs(flt(row.amount)) for row in paid_back)
	written = []

	for row in spent:
		if left <= 0:
			break

		back = min(left, flt(row.amount))
		card = frappe.get_doc("POS Gift Card", row.gift_card)
		entry = _write_entry(
			card,
			entry_type="refund",
			amount=back,
			# Read off the entry being reversed rather than worked out again: it
			# is the same card on the same bill, and it already knows.
			branch=row.branch,
			pos_profile=credit.pos_profile,
			sales_invoice=credit.name,
			reason=_("Returned from {0}").format(credit.return_against),
		)
		written.append(entry.name)
		left -= back

	return written


def card_rows(payments: list[dict]) -> list[dict]:
	"""The payment rows that spend a card, with the number they name."""
	rows = []
	for row in payments or []:
		if not is_gift_card_method(row.get("method")):
			continue

		number = (row.get("gift_card") or "").strip().upper()
		if not number:
			frappe.throw(_("Which gift card? Enter the number printed on it."))

		rows.append({**row, "gift_card": number})

	return rows


# --------------------------------------------------------------------------- #
# The ledger
# --------------------------------------------------------------------------- #


def _write_entry(
	card,
	*,
	entry_type: str,
	amount: float,
	branch: str | None,
	pos_profile: str | None,
	restaurant_order: str | None = None,
	sales_invoice: str | None = None,
	queue_id: str | None = None,
	reason: str | None = None,
	mode_of_payment: str | None = None,
	pos_opening_entry: str | None = None,
):
	"""One row, and the card's balance brought back in step with the rows."""
	entry = frappe.get_doc(
		{
			"doctype": "POS Gift Card Entry",
			"gift_card": card.name,
			"entry_type": entry_type,
			"amount": flt(amount),
			"restaurant_order": restaurant_order,
			"sales_invoice": sales_invoice,
			"branch": branch,
			"pos_profile": pos_profile,
			"recorded_by": frappe.session.user,
			"recorded_at": now_datetime(),
			"queue_id": queue_id,
			"mode_of_payment": mode_of_payment,
			"pos_opening_entry": pos_opening_entry,
			"reason": reason,
		}
	).insert(ignore_permissions=True)

	balance = _ledger_balance(card.name)
	entry.db_set("balance_after", balance, update_modified=False)
	frappe.db.set_value("POS Gift Card", card.name, "balance", balance, update_modified=False)
	return entry


def _already_done(queue_id: str | None) -> dict | None:
	"""The same request arriving twice returns what it did the first time (`09` §8)."""
	if not queue_id:
		return None

	existing = frappe.db.get_value(
		"POS Gift Card Entry", {"queue_id": queue_id}, ["gift_card", "amount"], as_dict=True
	)
	if not existing:
		return None

	return {
		"gift_card": existing.gift_card,
		"card_number": frappe.db.get_value("POS Gift Card", existing.gift_card, "card_number"),
		"amount": flt(existing.amount),
		"balance": _ledger_balance(existing.gift_card),
		"repeated": True,
	}

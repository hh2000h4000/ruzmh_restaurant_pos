# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Returns and refunds (FR-9, BR-050..BR-055).

**A return is the only way to reverse a sale** (`BR-050a`, `D-063`). Cancelling
the invoice is refused, because it reverses the ledger while telling nobody and
does not bring the cash back. A credit note is a document of its own, dated when
the money actually went back, which is what an auditor needs to see.

**Built on ERPNext's own return machinery**, never by hand. `make_return_doc`
sets `is_return`, `return_against`, the negative quantities, the taxes and —
the part that matters here — `sales_invoice_item` on every row, pointing at the
line it reverses. That field is how ERPNext itself measures what has already
come back, so partial returns are counted with the framework's own bookkeeping
rather than a parallel tally of ours (`FR-9.3`).

Refs: FR-9.1..FR-9.3, BR-050..BR-055, D-064
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime

from restaurant_pos.utils import addons, invoice_number, loyalty, numbering, payment, printing
from restaurant_pos.utils import gift_card as gift_cards
from restaurant_pos.utils.audit import log_audit
from restaurant_pos.utils.payment import TOLERANCE, terminal_methods
from restaurant_pos.utils.permissions import (
	consume_override_token,
	get_pos_permission_set,
	server_rights,
	validate_branch_access,
)
from restaurant_pos.utils.sale_doc import RETURNED_LINE, SALE, SALE_ITEM, WASTED
from restaurant_pos.utils.shift import assert_may_sell, selling_till
from restaurant_pos.utils.totals import money

#: Why a bill is being reversed, and what ZATCA calls that (D-065).
#:
#: **A coded list, not a typed sentence.** `FR-9.2` step 5 says "select return
#: reason from predefined list" and the first build shipped a text box — which
#: is not only off-spec but unsubmittable: a KSA credit note carries KSA-10, and
#: its text must map to one of **five legally recognised triggers**. Free text
#: cannot be relied on to, and "x" typed to get past a box certainly does not.
#:
#: The cashier still adds a note; it goes beside the code, never instead of it.
RETURN_REASONS = {
	"goods_returned": "goods return or service rejection",
	"quality_complaint": "goods return or service rejection",
	"wrong_item": "clerical error correction",
	"price_error": "clerical error correction",
	"order_cancelled": "cancellation or suspension of the supply",
}


def assert_returnable(order) -> str:
	"""BR-050 — there is nothing to return until there is an invoice."""
	if order.status != "closed" or not order.sales_invoice:
		frappe.throw(_("Order {0} has not been paid, so there is nothing to return.").format(order.name))

	if frappe.db.get_value(SALE, order.sales_invoice, "docstatus") != 1:
		frappe.throw(_("Invoice {0} is not submitted.").format(order.sales_invoice))

	return order.sales_invoice


def returnable(order) -> dict:
	"""Every line on a paid bill, and how much of it can still come back.

	`returned` is read from the credit notes themselves — one query over the
	rows that name these lines — so a second return sees what the first one
	took, and the screen never offers a quantity the server would refuse.
	"""
	invoice = assert_returnable(order)

	rows = frappe.get_all(
		SALE_ITEM,
		filters={"parent": invoice, "parenttype": SALE},
		fields=[
			"name",
			"idx",
			"item_code",
			"item_name",
			"qty",
			"rate",
			"amount",
			"rpos_order_item",
			"rpos_is_addon",
			"rpos_combo",
		],
		order_by="idx",
	)
	# `D-284` — an add-on comes back with its dish, never on its own.
	rows = addons.dish_rows(rows)

	taken = _returned_quantities([row.name for row in rows])
	# The lines sold by a recipe: their ingredients are on the bill itself.
	by_recipe = set(
		frappe.get_all(
			"Packed Item", filters={"parent": invoice, "parenttype": SALE}, pluck="parent_detail_docname"
		)
	)

	items = []
	for row in rows:
		returned = flt(taken.get(row.name))
		items.append(
			{
				"row": row.name,
				"idx": row.idx,
				"item": row.item_code,
				"item_name": row.item_name,
				"qty": flt(row.qty),
				"rate": flt(row.rate),
				"amount": flt(row.amount),
				"returned": returned,
				"returnable": flt(row.qty) - returned,
				# `D-328` — a line that took stock can be marked waste when it
				# comes back; unmarked, it goes back on the shelf. A line that
				# took none has nothing to mark.
				"moves_stock": row.name in by_recipe
				or bool(cint(frappe.get_cached_value("Item", row.item_code, "is_stock_item"))),
			}
		)

	return {
		"order_name": order.name,
		"sales_invoice": invoice,
		"items": items,
		# D-065 — the screen offers these and nothing else.
		"reasons": list(RETURN_REASONS),
		# BR-054, D-066 — every method the terminal has, because the cashier
		# chooses; the original is only what it opens on.
		"methods": refund_methods(order.pos_profile, _paid_with(invoice)),
		# BR-054 — the refund goes back the way the money came in, so the screen
		# needs to know what that was.
		"paid_with": _paid_with(invoice),
		"returns": _existing_returns(invoice),
		"fully_returned": all(row["returnable"] <= 0 for row in items),
		# BR-055, D-147 — said **before** the cashier commits, by the same
		# function that enforces it at Confirm.
		"needs_manager": needs_manager(order),
		# `D-326` — and the ways of refunding that need one whatever the shift.
		"manager_methods": manager_methods(order.pos_profile, _paid_with(invoice)),
	}


def _returned_quantities(rows: list[str]) -> dict[str, float]:
	"""How much of each original line has already come back.

	Quantities on a credit note are negative, so they are flipped here. Only
	submitted notes count: a draft is not a refund.
	"""
	if not rows:
		return {}

	taken: dict[str, float] = {}
	for row in frappe.get_all(
		SALE_ITEM,
		filters={RETURNED_LINE: ("in", rows), "docstatus": 1},
		fields=[RETURNED_LINE, "qty"],
	):
		taken[row[RETURNED_LINE]] = taken.get(row[RETURNED_LINE], 0.0) + abs(flt(row.qty))

	return taken


def _paid_with(invoice: str) -> list[dict]:
	return [
		{"method": row.mode_of_payment, "amount": flt(row.amount)}
		for row in frappe.get_all(
			"Sales Invoice Payment",
			filters={"parent": invoice, "parenttype": SALE},
			fields=["mode_of_payment", "amount"],
			order_by="idx",
		)
	]


def _existing_returns(invoice: str) -> list[dict]:
	return frappe.get_all(
		SALE,
		filters={"return_against": invoice, "docstatus": 1},
		fields=["name", "posting_date", "grand_total", "remarks"],
		order_by="creation",
	)


def create_return(
	order,
	*,
	items: list,
	reason_code: str,
	note: str | None = None,
	refund_method: str | None = None,
	override_token: str | None = None,
) -> dict:
	"""Refund part or all of a paid order (FR-9.2).

	``items`` is ``[{"row": <Sales Invoice Item name>, "qty": n}]`` — the row,
	not the item code, because the same dish can appear twice on one bill at two
	prices once modifiers are on it, and a refund has to name which.
	"""
	invoice = assert_returnable(order)

	# BR-044 — a refund out of a drawer that has been counted is the same defect
	# as a sale into one (D-055).
	assert_may_sell(order.pos_profile)

	# BR-052, and KSA-10 behind it (D-065).
	if reason_code not in RETURN_REASONS:
		frappe.throw(_("Choose why this is being returned."))

	reason = _reason_text(reason_code, note)
	paid_with = _paid_with(invoice)
	method = refund_method or (paid_with[0]["method"] if len(paid_with) == 1 else None)
	approved_by = _authorise_return(
		order, override_token, out_of_the_drawer=method in manager_methods(order.pos_profile, paid_with)
	)
	wanted = _validate_quantities(order, items)

	credit = _build_credit_note(order, invoice, wanted, reason, refund_method, _waste_choices(items))

	# D-189 — the points follow the money back, in the same transaction: what the
	# returned share earned is taken back and what it spent is given back.
	points = loyalty.reverse(order, credit, completes=_completes(invoice, {}))

	log_audit(
		"return_created",
		branch=order.branch,
		pos_profile=order.pos_profile,
		restaurant_order=order.name,
		approved_by=approved_by,
		reason=reason,
		details={
			"sales_invoice": invoice,
			"credit_note": credit.name,
			"reason_code": reason_code,
			"refund_amount": flt(credit.rounded_total or credit.grand_total),
			"items": [{"row": row, "qty": qty} for row, qty in wanted.items()],
		},
	)

	# **The customer leaves with the paper** (`D-143`). A sale prints its receipt
	# from `process_payment`; a refund printed nothing at all, so money went back
	# across the counter with no document — and the template has known how to
	# draw a credit note since it was written (`إشعار دائن`). Off the request
	# like every other print: the agent inside the restaurant is what reaches
	# paper (`D-084`).
	printing.enqueue_print("print_receipt", invoice_name=credit.name, order_name=order.name)

	return {
		"order_name": order.name,
		"sales_invoice": invoice,
		"credit_note": credit.name,
		"daily_number": credit.rpos_daily_number,
		# Positive, because a cashier hands this much back. The document carries
		# it negative, which is the ledger's business and not the screen's.
		"refund_amount": abs(flt(credit.rounded_total or credit.grand_total)),
		"returnable": returnable(order),
		**points,
	}


def _reason_text(reason_code: str, note: str | None) -> str:
	"""What goes on the credit note, and on the audit entry.

	The ZATCA trigger first, because that is the part a validator reads, then
	whatever the cashier added for the humans.
	"""
	detail = (note or "").strip()
	trigger = RETURN_REASONS[reason_code]
	return f"{trigger} ({reason_code}): {detail}" if detail else f"{trigger} ({reason_code})"


def _authorise_return(order, override_token: str | None, *, out_of_the_drawer: bool = False) -> str | None:
	"""BR-055 — an older shift's sale is a manager's decision.

	The permission alone covers a refund the cashier is making against their own
	open shift, where they can still see the customer. Anything from a shift that
	has been counted and handed over is somebody else's drawer, so it takes a
	manager's PIN even from a cashier who holds `can_create_return`.

	**And so does paying a platform's bill back out of the drawer** (`D-326`):
	the drawer never took that money.
	"""
	from restaurant_pos.utils.order import authorise

	approved_by = authorise("can_create_return", override_token)

	if (is_older_shift(order) or out_of_the_drawer) and not approved_by:
		approved_by = consume_override_token(override_token, "can_create_return")

	return approved_by


def manager_methods(pos_profile: str, paid_with: list[dict]) -> list[str]:
	"""The refund methods that need a manager's PIN on this bill (`D-326`).

	A bill a delivery platform collected goes back onto the platform's account;
	**any other way is the restaurant paying out money it never took** — a
	guest at the counter with a wrong order, made good in cash. The owner chose
	that it may happen, and that a manager says so: left to the cashier alone,
	a drawer comes up short by app orders refunded in notes and nobody sees why.
	"""
	owed = {row["method"] for row in paid_with if payment.is_credit_method(row["method"])}
	if not owed:
		return []
	return [method for method in refund_methods(pos_profile, paid_with) if method not in owed]


def is_older_shift(order) -> bool:
	"""Is this bill from a drawer that has already been counted? (`BR-055`)"""
	till = selling_till(order.pos_profile)
	current = frappe.db.get_value("POS Opening Entry", till.name, "rpos_restaurant_shift") if till else None

	return bool(order.restaurant_shift and order.restaurant_shift != current)


def needs_manager(order) -> bool:
	"""Will this refund be refused without a manager's PIN? (`D-147`)

	**Asked before the cashier commits, by the code that enforces it.** The rule
	was reachable only by pressing the button and being refused — and the return
	screen had nowhere to type a PIN, so the refusal was a wall: the till said
	"manager authorisation is required" and offered no way to give it.

	`D-125` is the standing rule this belongs to: every condition the server
	refuses at Confirm has to be visible on the screen before it.
	"""
	if not get_pos_permission_set().get("can_create_return"):
		return True

	return is_older_shift(order)


def _validate_quantities(order, items: list) -> dict[str, float]:
	"""FR-9.3 — never more than was sold, and never more than is left."""
	if not items:
		frappe.throw(_("Choose at least one item to return."))

	available = {row["row"]: row["returnable"] for row in returnable(order)["items"]}
	wanted: dict[str, float] = {}

	for entry in items:
		row = entry.get("row")
		qty = flt(entry.get("qty"))

		if row not in available:
			frappe.throw(_("Line {0} is not on this invoice.").format(row))

		if qty <= 0:
			frappe.throw(_("A return quantity must be greater than zero."))

		wanted[row] = wanted.get(row, 0.0) + qty

	for row, qty in wanted.items():
		if qty > flt(available[row]) + 0.0001:
			frappe.throw(
				_("Only {0} of that line is left to return.").format(flt(available[row])),
				frappe.ValidationError,
			)

	return addons.with_addons(order.sales_invoice, wanted)


def preview(order, *, items: list) -> dict:
	"""What this return would come to, before anybody commits to it (FR-9.2 §6).

	The figure is the credit note's own, computed by ERPNext's controller on a
	document that is never saved — not rate times quantity worked out on screen,
	which would leave out tax and rounding and quote the customer a number the
	invoice then disagreed with (`CLAUDE.md` §5.1).
	"""
	invoice = assert_returnable(order)
	credit = _compose(invoice, _validate_quantities(order, items))

	return {
		"order_name": order.name,
		"refund_amount": abs(flt(credit.rounded_total or credit.grand_total)),
		"net_amount": abs(flt(credit.net_total)),
		"tax_amount": abs(flt(credit.total_taxes_and_charges)),
	}


def _waste_choices(items: list) -> dict[str, bool]:
	"""sold line -> thrown away, for the lines the cashier said so about."""
	return {entry["row"]: bool(cint(entry["wasted"])) for entry in items if entry.get("wasted") is not None}


def _mark_wasted(credit, choices: dict[str, bool]) -> None:
	"""Say on each line whether it was thrown away: only where somebody said so.

	**Unsaid, it goes back on the shelf** (`D-328`) — for the till and for any
	other caller alike. Waste is the rare case and the one a person has to see:
	a guest who cancels before the kitchen starts has wasted nothing, and most
	returns are that or a sealed drink.

	**An add-on goes where its dish goes.** It comes back with the dish, never
	on its own (`D-284`), and the extra cheese on a burger that was binned was
	binned with it.
	"""
	of_dish: dict[str, int] = {}
	for row in credit.items:
		if cint(row.get("rpos_is_addon")):
			continue
		chosen = choices.get(row.get(RETURNED_LINE))
		row.set(WASTED, cint(chosen))
		if row.get("rpos_order_item"):
			of_dish[row.rpos_order_item] = row.get(WASTED)

	for row in credit.items:
		if cint(row.get("rpos_is_addon")):
			dish = of_dish.get(row.get("rpos_order_item"))
			row.set(WASTED, cint(dish))


def _compose(invoice: str, wanted: dict[str, float], wasted: dict[str, bool] | None = None):
	"""ERPNext builds it; we trim it to what is actually coming back.

	`make_return_doc` produces a full reversal of the invoice. Dropping the rows
	nobody asked for and reducing the rest is how a **partial** return is made
	without hand-building an accounting document (`10` critical note 9).

	Returns an unsaved document, so the same code answers both "what would this
	come to" and "do it" — one arithmetic, not two that can drift.
	"""
	from erpnext.controllers.sales_and_purchase_return import make_return_doc

	with server_rights():
		credit = make_return_doc(SALE, invoice)

	# A credit note counts on the same series as the terminal's sales (`D-309`):
	# one unbroken sequence per device is what ZATCA counts too.
	credit.naming_series = invoice_number.series_for(credit.pos_profile) or credit.naming_series

	kept = []
	for row in credit.items:
		qty = wanted.get(row.get(RETURNED_LINE))
		if not qty:
			continue

		# Negative, because a credit note takes goods back.
		row.qty = -abs(flt(qty))
		row.stock_qty = None
		kept.append(row)

	credit.set("items", kept)
	_mark_wasted(credit, wasted or {})
	_share_the_discount(credit, invoice, wanted)
	credit.set_missing_values()
	credit.calculate_taxes_and_totals()
	return credit


def _share_the_discount(credit, invoice: str, wanted: dict[str, float]) -> None:
	"""A partial return takes back its share of the bill's discount (`D-190`).

	`make_return_doc` copies the sale's **whole** `discount_amount` onto the
	credit note, which is right for a full return and wrong for every other one:
	one dish back off a discounted bill of two carried the entire reduction, and
	the customer was refunded the dish minus the discount on both. It has been
	so for every cashier's discount and every offer; loyalty found it, because a
	redemption is a discount (`D-189`).

	**By the value of the lines coming back**, before any reduction — the same
	measure `loyalty.reverse` uses for the points, so the money and the points
	come back in one proportion. And the return that empties the bill takes
	**whatever is left** rather than its own share, so a bill returned in parts
	gives back every riyal of its discount, not that less a halala of rounding.
	"""
	whole = abs(flt(frappe.db.get_value(SALE, invoice, "discount_amount")))
	if not whole:
		return

	if _completes(invoice, wanted):
		earlier = sum(
			abs(flt(amount))
			for amount in frappe.get_all(
				SALE,
				filters={"return_against": invoice, "docstatus": 1},
				pluck="discount_amount",
			)
		)
		share = whole - earlier
	else:
		sale = flt(frappe.db.get_value(SALE, invoice, "total"))
		coming_back = sum(abs(flt(row.qty)) * flt(row.rate) for row in credit.items)
		share = whole * coming_back / sale if sale else 0.0

	# Negative, like everything else on a credit note.
	credit.discount_amount = -flt(max(0.0, share), 2)


def _completes(invoice: str, wanted: dict[str, float]) -> bool:
	"""Whether nothing is left to return on the bill once `wanted` has come back.

	`wanted` is empty when the question is asked after the credit note is
	submitted, because `_returned_quantities` already counts it by then.
	"""
	rows = frappe.get_all(
		SALE_ITEM,
		filters={"parent": invoice, "parenttype": SALE},
		fields=["name", "qty"],
	)
	taken = _returned_quantities([row.name for row in rows])

	return all(flt(taken.get(row.name)) + flt(wanted.get(row.name)) >= flt(row.qty) - 0.0001 for row in rows)


def _build_credit_note(
	order,
	invoice: str,
	wanted: dict[str, float],
	reason: str,
	refund_method: str | None,
	wasted: dict[str, bool] | None = None,
):
	credit = _compose(invoice, wanted, wasted)

	_apply_refund(credit, refund_method)
	# The reason travels on the document, not only in our audit log: a KSA
	# credit note has to carry one, and this is where a ZATCA integration will
	# read it from (D-065).
	credit.remarks = _("Return of {0}: {1}").format(invoice, reason)

	# **Its own number, in the day's own sequence** (`D-143`). A return is an
	# invoice in reverse and a cashier reads a bill by its short number, not by
	# `ACC-SINV-2026-00042`: the sale is 20, returning part of it is 21, and
	# returning the rest later is 22. Three documents, three numbers, each
	# naming the bill it reverses.
	credit.rpos_daily_number = numbering.next_order_number(branch=order.branch, shift=order.restaurant_shift)

	credit.flags.ignore_permissions = True
	credit.insert()
	credit.submit()

	# `D-258` — and the money goes back where it came from. After the submit for
	# the reason the sale's own card entries come after the invoice (`D-256`): a
	# credit note that failed to post refunded nothing.
	gift_cards.refund(credit)
	return credit


def _apply_refund(credit, refund_method: str | None) -> None:
	"""BR-054, D-066 — **the cashier chooses**, cash or anything else.

	The original method is the default, because it is right most of the time and
	a customer usually wants their card credited. But it is only a default: a
	card terminal that has gone down, or a customer who would rather have the
	cash, are ordinary evenings in a restaurant, and refusing them would send the
	cashier to the ERPNext desk to do it by hand.

	**Never split by ratio.** A bill paid two ways has no right answer for one
	returned dish, and two part-refunds for one plate is a conversation nobody
	wants to have at a counter. One method, chosen.
	"""
	due = flt(credit.rounded_total or credit.grand_total)

	original = _paid_with(credit.return_against)
	method = refund_method or (original[0]["method"] if len(original) == 1 else None)

	if not method:
		frappe.throw(_("Choose how to refund this."))

	# The cap first: its refusal says *why* — "this bill was not paid with Cash" —
	# where the one below would call cash a method this terminal does not have.
	_assert_within_what_that_method_paid(credit, method, due, original)

	allowed = refund_methods(credit.pos_profile, original)
	if allowed and method not in allowed:
		frappe.throw(_("{0} is not a payment method on this terminal.").format(method))

	# D-029 — money that never entered a drawer does not come out of one. A
	# platform's order goes back onto the platform's account (`D-319`): the
	# reversal is paid with the same method, and no drawer opens for it.
	credit.is_pos = 1
	credit.set("payments", [])
	credit.append("payments", {"mode_of_payment": method, "amount": -abs(due)})
	# The mapped credit note still carries the **whole** bill as paid, and a
	# POS Invoice does not work it out again from the rows: a part return was
	# refused for paying back more than it came to. It pays back its own total.
	credit.paid_amount = credit.base_paid_amount = -abs(due)

	credit.set_posting_time = 1
	# **One instant, read once** (`D-261`). These were two calls to the clock, so
	# a correction landing between them could date the credit note from one
	# moment and time it from another — and on this machine the clock steps back
	# a second or so under load, measured. A single stamp cannot disagree with
	# itself.
	#
	# **And never before the sale it reverses.** ERPNext refuses a return dated
	# earlier than its invoice, so a step back landing between the sale and a
	# refund taken the same second refused the refund — the gate caught it.
	sold = frappe.db.get_value(SALE, credit.return_against, ["posting_date", "posting_time"])
	stamp = max(now_datetime(), get_datetime(f"{sold[0]} {sold[1]}"))
	credit.posting_date = stamp.date()
	credit.posting_time = stamp.time()

	# D-093 — a cash refund is money leaving the drawer, so the drawer opens.
	# The same rule as taking cash, for the same reason and in the same place as
	# the decision about which method it is.
	if payment.is_cash(method):
		printing.open_drawer(credit.pos_profile, reason=f"cash refund on {credit.return_against}")


def refund_methods(pos_profile: str, original: list[dict]) -> list[str]:
	"""What a refund of this bill may go back to: the terminal's methods, and what paid the bill.

	**The second half is for a delivery platform** (`D-325`). An order type
	forces its method — "HungerStation only" — without that method being one
	the terminal lists, so the bill was paid with something a refund could not
	then be sent back to.
	"""
	paid = list(dict.fromkeys(row["method"] for row in original))
	# **A bill a gift card touched goes back only the ways it was paid** (`D-340`).
	# Every other method is capped at nothing there (`D-258`), so offering Cash
	# was offering a button that could only be refused.
	if any(gift_cards.is_gift_card_method(method) for method in paid):
		return paid

	# **A platform that did not take this bill is not offered** (`D-330`). The
	# terminal lists HungerStation because its orders are rung up here, and that
	# put it on the refund sheet of every cash bill — where choosing it is
	# refused, in a sentence about a method that "paid 0.00".
	methods = [
		method
		for method in terminal_methods(pos_profile)
		if method in paid or not payment.is_credit_method(method)
	]
	return methods + [method for method in paid if method not in methods]


def _assert_within_what_that_method_paid(credit, method: str, due: float, original: list[dict]) -> None:
	"""A method may give back at most what it took (`D-258`).

	**The rule every professional till applies**, and the reason is a fraud path
	rather than tidiness: refunding cash for a bill settled by a gift card turns
	prepaid credit into notes, which is exactly how a card bought with a stolen
	payment card is cashed out. Toast refuses it outright on third-party cards;
	Square refunds to the original tender. So does this.

	**Only where the money was never in the drawer.** Everywhere else `D-066`
	still stands: the cashier chooses, because a dead card terminal or a guest
	who would rather have the notes is an ordinary evening.

	- **A bill a gift card touched:** every method is capped, with no way round.
	- **A refund onto a platform's account** (`D-325`): at most what the platform
	  took — a cash sale cannot be pushed onto HungerStation. Refunding a
	  platform's bill *another* way is not capped here; it takes a manager's
	  PIN instead (`D-326`).
	"""
	if not any(gift_cards.is_gift_card_method(row["method"]) for row in original) and not (
		payment.is_credit_method(method)
	):
		return

	paid = sum(flt(row["amount"]) for row in original if row["method"] == method)
	refunded = _already_refunded_to(credit.return_against, method)

	# **`abs`, because a credit note's total is negative** — it is a reversal.
	# Without it the comparison is a negative number against a positive cap and
	# passes whatever the figures are, which is how the first version of this
	# guard let a cash refund straight through its own test.
	if not paid:
		frappe.throw(
			_("This bill was not paid with {0}, so it cannot be refunded to it.").format(method),
			frappe.ValidationError,
		)

	if abs(flt(due)) > paid - refunded + TOLERANCE:
		frappe.throw(
			_(
				"{0} paid {1} on this bill. Refund that much to it, and the rest to what paid the rest."
			).format(method, f"{money(paid - refunded):.2f}"),
			frappe.ValidationError,
		)


def _already_refunded_to(invoice: str, method: str) -> float:
	"""What earlier credit notes against this bill already gave back that way."""
	credits = frappe.get_all(SALE, filters={"return_against": invoice, "docstatus": 1}, pluck="name")
	if not credits:
		return 0.0

	rows = frappe.get_all(
		"Sales Invoice Payment",
		filters={"parent": ("in", credits), "parenttype": SALE, "mode_of_payment": method},
		fields=["amount"],
	)
	return abs(sum(flt(row.amount) for row in rows))


def refund_detail(credit_note: str) -> dict:
	"""What one credit note actually took back (`D-171`).

	**The refund row on the orders list carried the sale's name**, so tapping it
	opened the sale: four items and positive money, on a row that said "refund"
	and showed a negative figure. The screen answered a question nobody asked,
	and the two items that came back were nowhere on it.

	The document was never wrong — the credit note holds exactly the returned
	rows at negative quantities, and printing it prints those. Only the screen
	was reading the wrong document.

	Read-only, and it stays that way: a credit note is submitted accounting. The
	one thing a cashier does with it here is look at it, and reprint it.
	"""
	credit = frappe.get_doc(SALE, credit_note)

	if not credit.is_return or credit.docstatus != 1:
		frappe.throw(_("{0} is not a refund.").format(credit_note))

	# **Authorised through the sale, exactly as the list is.** The credit note
	# has no branch of its own; the bill it reverses does, and that is what
	# decides who may read either of them.
	order = frappe.get_doc("Restaurant Order", {"sales_invoice": credit.return_against})
	validate_branch_access(order.branch)

	return {
		"credit_note": credit.name,
		"daily_number": credit.get("rpos_daily_number") or 0,
		# The bill it reverses, by the number a cashier reads it as.
		"returns_daily_number": order.daily_number,
		"order_name": order.name,
		"reason": credit.remarks or "",
		"refunded_at": credit.creation,
		# Negative, all of it, because that is the direction the money went —
		# and it is the document's own figure, not one worked out here.
		"total_amount": -abs(flt(credit.rounded_total or credit.grand_total)),
		"tax_amount": -abs(flt(credit.total_taxes_and_charges)),
		"items": [
			{
				"item": row.item_code,
				"item_name": row.item_name,
				"qty": flt(row.qty),
				"rate": flt(row.rate),
				"amount": flt(row.amount),
			}
			for row in credit.items
		],
	}

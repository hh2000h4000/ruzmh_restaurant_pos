# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Taking payment and turning an order into money.

``FR-2.7``: validate, create a submitted Sales Invoice in ERPNext, close the
order, release the table, and send the kitchen ticket for order types that hold
it until payment.

The invoice is built with ``is_pos = 1`` and its own ``payments`` rows, which is
how ERPNext settles a point-of-sale invoice. No separate Payment Entry is
created — that would pay the same invoice twice (``DECISIONS.md`` D-022).

ERPNext computes the invoice totals through its own controller (`10` critical
note 9). Where the order's running total and the invoice disagree, the invoice
wins, and it is the invoice figure that is returned to the cashier.

Refs: BR-016, BR-020..BR-024, FR-2.7, FR-10.2, FR-10.3, FR-10.4
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime

from restaurant_pos.utils import (
	activity,
	addons,
	combos,
	coupons,
	invoice_number,
	kitchen,
	loyalty,
	printing,
	promotions,
	totals,
)
from restaurant_pos.utils import gift_card as gift_cards
from restaurant_pos.utils.audit import log_audit
from restaurant_pos.utils.order import (
	assert_mutable,
	assert_transition,
	release_tables_of,
)
from restaurant_pos.utils.permissions import (
	assert_within_discount_limit,
	consume_override_token,
	discount_override_action,
	get_pos_permission_set,
)
from restaurant_pos.utils.sale_doc import SALE

#: Anything below this is float noise, not a shortfall (BR-022).
TOLERANCE = 0.005

#: Which ceiling a payment-screen discount is measured against (BR-031).
CEILING = "max_order_discount_pct"


def process_payment(
	order,
	*,
	payments: list,
	discount_type: str | None = None,
	discount_value: float = 0,
	promotion: str | None = None,
	override_token: str | None = None,
	loyalty_points: int = 0,
) -> dict:
	"""Settle an order and submit its Sales Invoice (FR-2.7)."""
	# BR-044 is in here too (D-058): taking money is the sale, not a step after
	# it, and a draft held over from an earlier shift must not be settled into a
	# drawer that has already been counted and handed over.
	assert_mutable(order)

	if not order.items or all(row.status == "void" for row in order.items):
		frappe.throw(_("An empty order cannot be paid."))

	blocker = invoice_blocker(order)
	if blocker:
		frappe.throw(blocker)

	payments = _normalise(payments)
	_apply_discount(order, discount_type, discount_value, override_token)
	_apply_promotion(order, promotion)

	# FR-10.5 — set on every payment, so the bill carries exactly what this one
	# spends and never a figure left over from an attempt that was refused.
	order.loyalty_points = max(0, cint(loyalty_points))

	totals.calculate(order)
	loyalty.assert_redeemable(order)
	_assert_tendered(order, payments)
	order.save(ignore_permissions=True)

	_validate_methods(order, payments)
	# `D-256` — before the invoice, not after: a bill posted against an empty
	# card is a sale with no money behind it, and undoing one is a credit note
	# somebody has to explain.
	gift_cards.assert_spendable(payments)
	settlement = _settlement_of(payments)
	change = _validate_amounts(order, payments) if settlement == "till" else 0.0

	invoice = _create_sales_invoice(order, payments, settlement)
	_assert_invoice_matches_order(order, invoice)

	# BR-016 — closed only once the invoice is submitted.
	assert_transition(order, "closed")
	order.sales_invoice = invoice.name
	order.status = "closed"
	order.closed_at = now_datetime()

	# D-189 — after the invoice and inside its transaction: points move only if
	# the sale posts, and a refused sale leaves the balance where it was.
	points = loyalty.settle(order, invoice)

	# `D-248` — and the coupon is spent here for the same reason: a code typed
	# onto a bill that was then cancelled was never used.
	coupons.consume(order)

	# `D-256` — and the cards, for the third time the same reason.
	gift_cards.settle(order, invoice, payments)

	# **The bill is filed under whoever took the money** (`D-188`).
	#
	# It used to keep the person who *opened* it, and that is the wrong one for
	# everything this field is used for. The money is physically in this
	# cashier's drawer, and `summarise_till` attributes a drawer's takings by
	# `cashier` — so a bill opened by somebody who then went home was counted
	# against their closed drawer and missing from the one the notes are
	# actually sitting in. The count comes up over, and nobody can say why.
	#
	# Nothing is lost by overwriting it: Frappe's own `owner` records who
	# created the order, and the bill's story carries `opened` with their name
	# (`D-106`). The user's rule, in their words: الفاتورة تسجل باسم اللي
	# أغلقها وليس اللي فتحها.
	order.cashier = frappe.session.user
	# **And the drawer the notes went into** (`D-227`). The shift report used to
	# reconstruct this from the terminal, the cashier and the drawer's own window
	# — right, but derived: a corrected opening time moved bills between drawers,
	# and nothing on a bill could answer "which count was this in?". It is known
	# here, at the one moment money changes hands, so it is written here.
	# Imported here: `shift` reads `is_credit_method` from this module, and a
	# module-level import either way closes the circle.
	from restaurant_pos.utils.shift import selling_till

	drawer = selling_till(order.pos_profile)
	order.pos_opening_entry = drawer.name if drawer else None
	# **Never before the drawer it went into** (`D-297`, the family of `D-261`).
	# A clock stepped back by NTP stamped a bill paid in the second after the
	# drawer opened *earlier* than the opening, and the drawer's window, which
	# reads `closed_at`, left the notes out of what it expected to hold.
	if drawer and get_datetime(order.closed_at) < get_datetime(drawer.period_start_date):
		order.closed_at = drawer.period_start_date
	order.save(ignore_permissions=True)

	# BR-061 / FR-2.7g — the table is not free until it has been cleaned, and not
	# even then while another bill is still open on it (`BR-066`). **Every** table
	# the bill was holding, because a party across two of them is one bill
	# (`BR-063`) and paying it is what reverses the join.
	release_tables_of(order, to="cleaning")

	# D-191 — a party seated from a booking has paid: the booking is done.
	from restaurant_pos.utils import reservation

	reservation.complete(order)

	kots = _send_kitchen_if_due(order)

	if flt(order.discount_amount):
		# 08 §5 — a discount is a sensitive action even when it was within limits.
		log_audit(
			"discount_applied",
			branch=order.branch,
			pos_profile=order.pos_profile,
			restaurant_order=order.name,
			approved_by=order.discount_approved_by,
			details={
				"sales_invoice": invoice.name,
				"discount_type": order.discount_type,
				"discount_value": flt(order.discount_value),
				"discount_amount": flt(order.discount_amount),
			},
		)

	# FR-7.5 — the receipt goes with the payment, not with a button somebody has
	# to remember. Off the request: the agent inside the restaurant is what
	# reaches paper (D-084), and rendering must not be added to the sale.
	printing.enqueue_print("print_receipt", invoice_name=invoice.name, order_name=order.name)

	# D-093 — cash has to go in and change has to come out, so the drawer opens
	# on a cash payment and only on a cash payment. Opening it for a card sale
	# is how a drawer ends up sitting open through a queue.
	if any(is_cash(row["method"]) for row in payments):
		printing.open_drawer(order.pos_profile, reason=f"cash payment on {order.name}")

	activity.log(
		order,
		"paid",
		subject=f"{flt(invoice.rounded_total or invoice.grand_total):.2f}",
		details={
			"sales_invoice": invoice.name,
			"settlement": settlement,
			"methods": [row["method"] for row in payments],
			"change": change,
		},
	)

	return {
		"order_name": order.name,
		"sales_invoice": invoice.name,
		# The invoice is authoritative (D-018), so this is the invoice's figure.
		"total_amount": flt(invoice.rounded_total or invoice.grand_total),
		"change_amount": change,
		"settlement": settlement,
		# What the customer still owes: zero at the till, the full amount on
		# account until the monthly statement is settled.
		"outstanding_amount": flt(invoice.outstanding_amount),
		"status": order.status,
		"kots_created": kots,
		# What the bill earned and what the customer now holds — empty when the
		# bill is outside the scheme, which the screen reads as nothing to say.
		**points,
	}


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


#: Half a halala. Below this the two figures are the same number arrived at by
#: different routes, not a disagreement.
TOTALS_EPSILON = 0.005


def _assert_invoice_matches_order(order, invoice) -> None:
	"""The bill the customer was quoted must be the bill ERPNext posts (`D-091`).

	The two are computed by different code — `totals.compute` for the screen,
	ERPNext's controller for the ledger — and the whole design depends on them
	agreeing. Nothing checked, so when the tax template's
	`included_in_print_rate` was dropped on the way to the invoice, the order
	said 32.00, ERPNext billed 36.80, the cashier took 32.00 and the invoice sat
	4.80 outstanding. **No error anywhere**; the money simply stopped matching,
	and a shop would find out at the monthly reconciliation.

	`frappe.throw` here rolls the invoice back, which is the point: a bill that
	cannot be priced consistently must not become a posted document somebody has
	to unpick later. The offline replay already had this guard
	(`offline._assert_totals_agree`); the ordinary payment did not.
	"""
	quoted = flt(order.total_amount)
	posted = flt(invoice.rounded_total or invoice.grand_total)

	if abs(quoted - posted) < TOTALS_EPSILON:
		return

	frappe.throw(
		_(
			"This bill prices differently on the screen ({0}) and on the invoice ({1}). "
			"Nothing has been charged. A manager should check the terminal's tax template."
		).format(quoted, posted)
	)


def block_invoice_cancel(doc, method=None) -> None:
	"""A POS sale is reversed by a return, never by cancelling it (D-063).

	Hooked on ``Sales Invoice.before_cancel``. Deleting a submitted invoice
	needs a cancellation first, so this covers that too.

	**Why refuse rather than react.** Cancelling from the desk left the till and
	the books disagreeing: the ledger reversed the sale and the order still said
	``closed`` (D-062). Making the order follow the invoice is worse — reopening
	a bill after its drawer was counted re-creates every hole BR-044 closes. And
	the money is already gone from the drawer either way: an invoice cancelled
	an hour after the customer walked out does not bring the cash back.

	A return (``FR-9``) is the honest reversal: it is a credit note, a document
	of its own, dated when the money actually went back — which is what an
	auditor needs to see. It is `is_return = 1` on a **new** invoice, so nothing
	here stands in its way.
	"""
	order = frappe.db.get_value("Restaurant Order", {"sales_invoice": doc.name}, "name")
	if not order:
		return

	frappe.throw(
		_("Invoice {0} was issued for order {1}. Reverse it with a return, not a cancellation.").format(
			doc.name, order
		),
		title=_("A point-of-sale invoice is not cancelled"),
	)


def _normalise(payments) -> list[dict]:
	if isinstance(payments, str):
		payments = frappe.parse_json(payments)

	# Nothing tendered is not refused here: whether a bill needs a tender is
	# only known once its offers and discounts are applied (`_assert_tendered`).
	rows = []
	for row in payments:
		amount = flt(row.get("amount"))
		if amount <= 0:
			frappe.throw(_("A payment amount must be greater than zero."))

		rows.append(
			{
				"method": row.get("method") or row.get("mode_of_payment"),
				"amount": amount,
				# FR-10.3 — what the customer handed over, for change.
				"tendered": flt(row.get("tendered") or amount),
				# `D-256` — which card this row spends. Every other method takes
				# money from somewhere the row need not name; a gift card names
				# the exact balance it comes off.
				"gift_card": (row.get("gift_card") or "").strip().upper() or None,
			}
		)

	return rows


def invoice_blocker(order) -> str | None:
	"""Why this order can never become an invoice, whatever is tendered (`D-125`).

	Not a check on what the cashier typed — those belong on the buttons — but a
	setup fault no tender can get past. A POS Profile with no default customer
	used to surface as a `throw` from inside `_create_sales_invoice`, which is
	*after* the customer has counted out the money and the drawer is open. It is
	the shop's configuration, known the moment the order is loaded, so the
	payment screen asks for it when it opens and says so instead of offering
	methods.

	One function, two callers: `get_payment_summary` to warn, `process_payment`
	to refuse. A condition remembered in two places is a condition forgotten in
	one (`CLAUDE.md` §5.5).
	"""
	profile = frappe.get_cached_doc("POS Profile", order.pos_profile)

	if not (order.customer or profile.customer):
		return _("Set a default customer on POS Profile {0} before taking payment.").format(order.pos_profile)

	return _stock_that_is_not_there(order, profile)


def _stock_that_is_not_there(order, profile) -> str | None:
	"""A dish ERPNext keeps stock for, with none in the warehouse (`D-232`, `D-233`).

	The invoice moves stock (`04` §6), so a line whose item is stock-tracked and
	whose warehouse holds nothing stops the sale — in ERPNext's own words, in
	the middle of Confirm, with the money already counted out. The user met it
	on a coffee: *1.0 units of Turkish Coffee are required in Finished Goods to
	complete this transaction.*

	**The rule is ERPNext's own**, not a second opinion of ours:
	`is_negative_stock_allowed` is what its POS asks before refusing a row, and
	it answers yes for an item marked *Allow Negative Stock* and for a site that
	allows it everywhere. A restaurant selling faster than it can enter
	deliveries marks the item, keeps its cost and its purchases, and is never
	stopped in front of a queue (`D-233`).

	What we add is **when** it is said: on the payment screen as it opens rather
	than inside Confirm (`D-125`).
	"""
	from erpnext.stock.stock_ledger import is_negative_stock_allowed

	wanted: dict[str, float] = {}
	for row in order.items or []:
		if row.status != "void":
			# A combo is not stocked; its items are, and they are among the add-ons.
			if not combos.parts(row):
				wanted[row.item] = wanted.get(row.item, 0.0) + flt(row.qty)
			# `D-284` — an add-on leaves stock like the dish does, in its stock unit.
			for item, qty in addons.stock_taken(row).items():
				wanted[item] = wanted.get(item, 0.0) + qty
	if not wanted:
		return None

	tracked = frappe.get_all(
		"Item",
		filters={"name": ("in", list(wanted)), "is_stock_item": 1},
		fields=["name", "item_name"],
	)
	if not tracked:
		return None

	warehouse = profile.warehouse
	bins = {
		row.item_code: row
		for row in frappe.get_all(
			"Bin",
			filters={"item_code": ("in", [row.name for row in tracked]), "warehouse": warehouse},
			fields=["item_code", "actual_qty", "valuation_rate"],
		)
	}

	for row in tracked:
		held = bins.get(row.name)
		name = row.item_name or row.name

		if flt(held.actual_qty if held else 0) >= wanted[row.name]:
			continue

		if not is_negative_stock_allowed(item_code=row.name):
			return _(
				"{0} is kept in stock and {1} has none. Enter its stock, or tick Allow Negative Stock on the item."
			).format(name, warehouse)

		# **Selling below zero still has to be costed** (`D-234`) — but only where
		# ERPNext itself would refuse. It posts the cost of goods sold from a
		# valuation rate, and an item never received has none, so the invoice is
		# refused inside Confirm in a paragraph about accounting entries, with
		# the money already taken.
		#
		# **Its rule, asked of it** (`D-235`): the refusal needs perpetual
		# inventory *and* nothing to fall back on — and its fallbacks are wider
		# than a valuation rate: the last ledger entry, then the item's valuation
		# rate, then its standard rate, then a buying price. Our own shortcut
		# knew two of those, so it warned about sales ERPNext would have posted.
		if _erpnext_would_refuse(row.name, warehouse, profile):
			return _("{0} has no valuation rate. Enter the cost of one unit on the item.").format(name)

	return None


def _erpnext_would_refuse(item: str, warehouse: str, profile) -> bool:
	"""Whether ERPNext would stop this line for want of a cost.

	Asked of ERPNext rather than answered here: one rule, one place
	(`CLAUDE.md` §5.5), and this one has four fallbacks and a company setting in
	it. `raise_error_if_no_rate=False` makes it report rather than throw.
	"""
	import erpnext
	from erpnext.stock.stock_ledger import get_valuation_rate

	if not erpnext.is_perpetual_inventory_enabled(profile.company):
		return False

	return not flt(
		get_valuation_rate(
			item,
			warehouse,
			SALE,
			"",
			currency=profile.currency,
			company=profile.company,
			raise_error_if_no_rate=False,
		)
	)


def is_credit_method(method: str) -> bool:
	"""Whether this method leaves the money owed rather than collected.

	A delivery platform has already taken the customer's money; a corporate
	account will pay on a statement. Either way nothing enters the till
	(``DECISIONS.md`` D-029).
	"""
	return bool(frappe.db.get_value("Mode of Payment", method, "rpos_is_credit"))


def is_cash(method: str) -> bool:
	"""Whether notes and coins actually change hands (`D-093`).

	ERPNext's own `Mode of Payment.type`, not a name match: a restaurant may call
	the method "نقدي" or "Cash on delivery" or anything else, and the drawer must
	open on what the method *is* rather than on how it is spelled.
	"""
	return frappe.db.get_value("Mode of Payment", method, "type") == "Cash"


def _assert_tendered(order, payments: list[dict]) -> None:
	"""A bill that costs something needs a tender; one that costs nothing does not.

	A coupon for a free coffee, with nothing else bought, leaves a bill of zero —
	and the screen could not close it: there was nothing to pay and it insisted
	on a payment. Toast closes a fully comped check at zero, and ERPNext's own
	`validate_pos_paid_amount` refuses a POS invoice without payments **only
	when its total is above zero**. So the sale still posts, as a zero invoice
	that carries the item and the discount that took it to nothing — which is
	what an auditor and the promotion report both need to see.
	"""
	if not payments and flt(order.total_amount) > TOLERANCE:
		frappe.throw(_("Select at least one payment method."))


def _settlement_of(payments) -> str:
	"""``"credit"`` or ``"till"`` — an order is one or the other, never both.

	Splitting a bill half to a delivery platform and half in cash is not a
	thing that happens, and allowing it would put a partly-outstanding invoice
	in a cash drawer reconciliation. If a real case appears, it needs its own
	design rather than falling out of a loop.
	"""
	kinds = {"credit" if is_credit_method(row["method"]) else "till" for row in payments}

	if len(kinds) > 1:
		frappe.throw(_("An order is either settled at the till or billed to an account, not both."))

	# A bill of zero took nothing, so it settles itself at the till.
	return kinds.pop() if kinds else "till"


def terminal_methods(pos_profile: str) -> list[str]:
	"""The payment methods set on the terminal, in the order the manager put them.

	**Not filtered by ERPNext's `allow_in_returns`.** That field exists on
	`POS Payment Method` and defaults to `0`, so gating a refund on it would ship
	a terminal that can refund nothing at all — measured on both sites, where
	every row carries zero (BR-054, D-066).
	"""
	return frappe.get_all(
		"POS Payment Method",
		filters={"parent": pos_profile, "parenttype": "POS Profile"},
		pluck="mode_of_payment",
		order_by="idx",
	)


def allowed_methods(order) -> list[dict]:
	"""What this bill may be paid with (BR-023, BR-002, D-224).

	**The order type when it names methods, else the terminal's.** An app's
	type names its own method, and that settles it. Every other type fell back
	to *every enabled Mode of Payment*, so a till set up to take cash showed
	Cheque, Wire Transfer and Bank Draft beside it — the user: "only what I
	choose should show". The terminal's list is that choice, and it is mandatory
	on the POS Profile, so there is always one.

	One answer for the screen and for Confirm: the list the cashier is offered
	is the list the server accepts.
	"""
	rows = frappe.get_all(
		"OT Payment Method",
		filters={"parent": order.order_type, "parenttype": "Restaurant Order Type"},
		fields=["payment_method", "is_forced", "is_default"],
		order_by="idx",
	)
	if rows:
		return rows

	return [
		{"payment_method": method, "is_forced": 0, "is_default": 0}
		for method in terminal_methods(order.pos_profile)
	]


def _validate_methods(order, payments) -> None:
	"""BR-023 / BR-002 — only the methods this bill is offered may pay it."""
	allowed = allowed_methods(order)

	forced = [row["payment_method"] for row in allowed if row["is_forced"]]
	permitted = {row["payment_method"] for row in allowed}

	for row in payments:
		if not frappe.db.exists("Mode of Payment", row["method"]):
			frappe.throw(_("Unknown payment method: {0}").format(row["method"]))

		if row["method"] not in permitted:
			frappe.throw(_("{0} is not accepted for this order type.").format(row["method"]))

		if forced and row["method"] not in forced:
			# An app order is settled by the app; letting a cashier take cash for
			# it would put money in the till that the platform also pays out.
			frappe.throw(_("This order type must be paid by {0}.").format(forced[0]))


def _validate_amounts(order, payments) -> float:
	"""BR-022 — payment must cover the total in full. Returns the change (BR-021)."""
	due = flt(order.total_amount)
	paid = sum(row["amount"] for row in payments)

	if paid + TOLERANCE < due:
		frappe.throw(_("Payment of {0} does not cover the total of {1}.").format(paid, due))

	tendered = sum(row["tendered"] for row in payments)
	if tendered + TOLERANCE < paid:
		frappe.throw(_("The amount received is less than the amount being paid."))

	return totals.money(max(tendered - due, 0))


def _apply_discount(order, discount_type, discount_value, override_token) -> None:
	"""FR-10.4 / BR-031 — a discount beyond the cashier's ceiling needs a manager."""
	if not discount_type or not flt(discount_value):
		return

	# **The offer said it does not combine, and now something enforces it**
	# (`D-169`). Checked before the ceiling, because "you may not discount this
	# bill at all" is a different answer from "not that much", and a cashier told
	# the second one goes looking for a manager who cannot help.
	exclusive = promotions.blocks_a_discount(order)
	if exclusive:
		frappe.throw(_("{0} does not combine with a manual discount.").format(exclusive))

	percentage = discount_percentage(order, discount_type, discount_value)

	if percentage > flt(get_pos_permission_set().get(CEILING)):
		if not override_token:
			# Raises with the cashier's own limit in the message.
			assert_within_discount_limit(CEILING, percentage)

		# The token is bound to this exact percentage, so an approval obtained
		# for a small discount cannot be spent on a large one.
		order.discount_approved_by = consume_override_token(
			override_token, discount_override_action(CEILING, percentage)
		)

	order.discount_type = discount_type
	order.discount_value = flt(discount_value)


def discount_percentage(order, discount_type: str | None, discount_value: float) -> float:
	"""What the requested discount is worth as a percentage of the subtotal.

	A flat amount still has to be measured against the cashier's percentage
	ceiling, or `BR-031` would be bypassed by entering riyals instead of a rate.
	"""
	if not discount_type or not flt(discount_value):
		return 0.0

	if discount_type == "percentage":
		return flt(discount_value)

	subtotal = flt(order.subtotal)
	return flt(discount_value) / subtotal * 100 if subtotal else 0.0


# --------------------------------------------------------------------------- #
# ERPNext
# --------------------------------------------------------------------------- #


def _apply_promotion(order, promotion: str | None) -> None:
	"""Record the promotion a cashier picked by hand (`FR-11.2`, `D-165`).

	Two checks, and the screen is neither of them (`CLAUDE.md` §5.4):

	1. **The right to choose.** A promotion is the shop's money, and picking one
	   by hand is deciding to spend it — the same class of act as a discount
	   beyond a ceiling, and guarded by the same right a discount approver must
	   hold, `can_manual_promotion`.
	2. **That it is actually on offer for this bill.** Without it a cashier could
	   name any promotion in the system — an expired one, or one scoped to
	   another branch — and the engine would honour it, which turns every
	   condition on the record into a suggestion.

	Refused rather than ignored. A promotion the customer was told about and
	that then silently did not apply is the report nobody can act on (`D-074`).
	"""
	if not promotion:
		return

	if not get_pos_permission_set().get("can_manual_promotion"):
		frappe.throw(_("You are not allowed to choose a promotion by hand."))

	from restaurant_pos.utils import promotions

	if promotion not in {offer["name"] for offer in promotions.offers_for(order)}:
		frappe.throw(_("That promotion does not apply to this bill."))

	order.chosen_promotion = promotion

	# **Audited, because a person did it** (`D-172`). An automatic offer is the
	# shop's own rule firing and the bill's story is the whole record of it;
	# choosing one by hand is somebody spending the shop's money under a
	# permission, which is the same class of act as a discount beyond a ceiling
	# and belongs in the compliance log beside it (`08` §5).
	log_audit(
		"promotion_applied",
		branch=order.branch,
		pos_profile=order.pos_profile,
		restaurant_order=order.name,
		reason=promotion,
		details={"promotion": promotion},
	)


def _create_sales_invoice(order, payments, settlement: str = "till"):
	"""Build and submit the invoice through ERPNext's own controller.

	Never bypassed (`10` critical note 9): the controller is what computes tax,
	posts the ledger, moves stock and gives ZATCA integrations something to sign.
	"""
	profile = frappe.get_cached_doc("POS Profile", order.pos_profile)
	# Guaranteed to exist: `process_payment` refuses the sale on `invoice_blocker`
	# before anything is charged, and the payment screen says so before that.
	customer = order.customer or profile.customer

	invoice = frappe.new_doc(SALE)
	invoice.update(
		{
			# Branch, terminal, count — and a counter per terminal, so tills do
			# not queue behind one (`D-309`). None leaves ERPNext's own series.
			"naming_series": invoice_number.series_for(profile.name) or invoice.naming_series,
			"customer": customer,
			"company": profile.company,
			"pos_profile": profile.name,
			# A till sale settles itself through the `payments` table. A credit
			# sale must stay outstanding against the customer, so it is an
			# ordinary invoice and a Payment Entry clears it at month end
			# (D-022, D-029).
			"is_pos": 1 if settlement == "till" else 0,
			"currency": profile.currency,
			"selling_price_list": profile.selling_price_list,
			"set_posting_time": 1,
			"posting_date": now_datetime().date(),
			"posting_time": now_datetime().time(),
			# **Nothing leaves the warehouse here** (`D-308`). A POS Invoice
			# records the recipe as it stood — ERPNext unpacks it onto the bill —
			# and the posting takes the stock from that record, once for the day.
			"set_warehouse": profile.warehouse,
			# **The till prices the bill; ERPNext's pricing rules do not** (`D-284`).
			# Every price here was fixed on the order, and the guard below refuses
			# an invoice that disagrees with it — so a rule could only ever break
			# a sale. And a transaction rule that does not match *removes* every
			# `is_free_item` line, which is how a free add-on is written.
			"ignore_pricing_rule": 1,
			"taxes_and_charges": profile.taxes_and_charges,
			"cost_center": profile.get("cost_center"),
			"remarks": _("Restaurant Order {0}").format(order.name),
		}
	)

	if profile.taxes_and_charges:
		invoice.set(
			"taxes",
			frappe.get_all(
				"Sales Taxes and Charges",
				filters={"parent": profile.taxes_and_charges},
				# `included_in_print_rate` is not optional here (`D-091`). Copying
				# the row without it turns a tax-inclusive template into an
				# exclusive invoice: the order says 32.00, ERPNext bills 36.80,
				# and the payment leaves 4.80 outstanding on a bill the customer
				# has already settled in full. Nothing raises — the money simply
				# stops matching.
				fields=[
					"charge_type",
					"account_head",
					"description",
					"rate",
					"cost_center",
					"included_in_print_rate",
				],
				order_by="idx",
			),
		)

	for row in order.items:
		if row.status == "void":
			continue

		# `D-284` — the dish, then every add-on it sells as a line of its own;
		# `D-285` — or a combo's items, sharing its price.
		lines = combos.invoice_lines(row) if combos.parts(row) else addons.invoice_lines(row)
		for line in lines:
			invoice.append(
				"items",
				{**line, "warehouse": profile.warehouse, "cost_center": profile.get("cost_center")},
			)

	if flt(order.discount_amount):
		# Which total the discount comes off has to match how the order was
		# priced, or the invoice and the till disagree on every discounted bill
		# (`D-091`).
		#
		# Exclusive: `FR-10.4` — the discount reduces the net and ERPNext
		# recomputes VAT on what is left.
		#
		# Inclusive: the cashier took a percentage off the price the customer
		# was shown, which already contains the tax. That is the grand total, and
		# `totals.compute` subtracts it from the same figure.
		invoice.apply_discount_on = (
			"Grand Total" if totals.tax_is_inclusive(order.pos_profile) else "Net Total"
		)
		invoice.discount_amount = flt(order.discount_amount)

	for row in payments:
		invoice.append("payments", {"mode_of_payment": row["method"], "amount": row["amount"]})

	if not payments:
		# A bill that came to nothing closes with no tender (`D-275`) — and a POS
		# Invoice will not be saved without a payment row. So it carries one, for
		# nothing, on the terminal's own first method: the document is true, and
		# no drawer is expected to hold anything for it.
		invoice.append("payments", {"mode_of_payment": profile.payments[0].mode_of_payment, "amount": 0})

	# **The promotion that applied, read off the order** (`D-165`). This used to
	# be a string the client sent, written onto a submitted financial document
	# with nothing checking it — it named a promotion that need not exist, while
	# the total it claimed to explain was worked out from something else
	# entirely. What goes on the invoice now is the promotion the engine
	# actually used, or nothing.
	if order.promotion:
		title = frappe.db.get_value("Restaurant Promotion", order.promotion, "title")
		invoice.remarks = f"{invoice.remarks} | {_('Promotion')}: {title or order.promotion}"

	# The figure alone is a discount nobody can explain from the invoice; the
	# remark names what paid for it, as the promotion's does.
	if cint(order.get("loyalty_points")):
		invoice.remarks = f"{invoice.remarks} | {_('Loyalty points')}: {cint(order.loyalty_points)}"

	invoice.flags.ignore_permissions = True
	invoice.insert()
	invoice.submit()
	return invoice


def _send_kitchen_if_due(order) -> list:
	"""FR-2.7e — order types configured to hold the ticket until payment.

	**And a ``save`` type paid before it was put down** (`D-223`). That type sends
	when the cashier leaves the bill; paying straight from the bill is leaving it
	too, and the only moment the server sees. Without this, a takeaway rung up
	and paid in one go would reach the customer and never the kitchen.
	"""
	when = frappe.db.get_value("Restaurant Order Type", order.order_type, "send_to_kitchen_on")
	if when not in ("payment", "save"):
		return []

	if not any(row.status == "pending" for row in order.items):
		return []

	return kitchen.send_to_kitchen(order)["kots_created"]

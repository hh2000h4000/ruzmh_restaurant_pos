# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Loyalty points: earned on a paid bill, spent as a discount on a later one.

**ERPNext's ledger, our arithmetic** (`D-189`). The program and every movement
of points live in ERPNext's own `Loyalty Program` and `Loyalty Point Entry`
(`BR-080`), so the desk, the customer's dashboard and any report read the same
rows. What ERPNext does *with* them on a Sales Invoice is not used, for four
reasons measured or read on this bench — the whole case is in
`docs/12_Loyalty_Points.md`:

1. **It redeems as a payment.** ZATCA's business-promotions guideline treats a
   shop's own points spent on its own goods as a **discount**: VAT on what is
   left, not on the full price. Here the points travel the road the cashier's
   discount and the offers already use, so the invoice, its VAT and the QR all
   carry the reduced figure.
2. **Its tiers pick the wrong one** — six of nine spends measured on the test
   site landed a tier too high. Tiers are refused (:func:`validate_program`).
3. **A return stops dead** when the points its bill earned were spent since,
   and even a partial return hands back every point the bill spent.
4. **An empty expiry kills the points the day they are earned**, and they are
   earned on the VAT-inclusive total.

**The ledger's one rule.** Every row is either a *grant* — points arriving,
nothing in `redeem_against` — or a *movement against a grant*, naming it there.
Spending walks the grants soonest-to-expire first; a return claws back from the
grant its own bill earned. So what is left on a grant is always the grant plus
the movements naming it, and a movement expires with its grant.

Refs: BR-080..BR-084, FR-10.5, D-189
"""

import math

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import add_days, cint, flt, getdate, today

from restaurant_pos.utils.sale_doc import SALE

LEDGER = "Loyalty Point Entry"

#: Below this a quotient is float noise, not a missing point: 15.00 / 0.05 is
#: 299.99999999999997 in binary, and flooring it would cost the guest a point.
_NOISE = 1e-6


# --------------------------------------------------------------------------- #
# The program
# --------------------------------------------------------------------------- #


def validate_program(doc, method=None) -> None:
	"""Hooked on ``Loyalty Program.validate`` — refuse what RPOS cannot honour.

	Each refusal is a program that would otherwise save cleanly and then behave
	in a way nobody configured. Said when the manager presses Save, not
	discovered by a guest at the counter (`D-125`).
	"""
	if doc.loyalty_program_type == "Multiple Tier Program":
		# ERPNext's tier function puts a guest one tier above the one they reached
		# — measured, `D-189` — and RPOS does not compute tiers of its own yet.
		frappe.throw(_("Restaurant POS runs single-tier loyalty programs. Tiers are not supported yet."))

	rules = doc.get("collection_rules") or []
	if len(rules) != 1 or flt(rules[0].collection_factor) <= 0:
		frappe.throw(_("Set one collection rule: how much a customer spends to earn one point."))

	if flt(doc.conversion_factor) <= 0:
		frappe.throw(_("Set what one point is worth when it is spent."))

	if cint(doc.expiry_duration) <= 0:
		# ERPNext stamps each grant with posting date + this many days, so zero
		# is not "never" — it is "tonight".
		frappe.throw(
			_("Set how many days points last. Left empty, they would expire the day they are earned.")
		)

	percent = flt(doc.get("rpos_max_redeem_percent"))
	if not 0 < percent <= 100:
		frappe.throw(_("The share of a bill points may pay must be between 1 and 100 percent."))

	if cint(doc.get("rpos_min_redeem_points")) < 0:
		frappe.throw(_("The minimum balance to spend points cannot be negative."))


def keep_erpnext_out(doc, method=None) -> None:
	"""Hooked on ``Sales Invoice.validate`` — an RPOS invoice's points are ours.

	**`Sales Invoice.loyalty_program` is fetched from the customer on every save**
	— `fetch_from`, and not only when empty. So every bill for an enrolled
	customer reached ERPNext's `on_submit` carrying the program, and ERPNext
	granted its own points, on the VAT-inclusive total, beside the ones written
	here: measured, the balance came out doubled. On a return it went further and
	refused the refund outright once those points had been spent.

	Cleared here because a `validate` hook runs **after** the fetch and before
	`on_submit`, on insert and again on submit. Only for an invoice from an RPOS
	terminal; one raised in the desk keeps ERPNext's own behaviour.
	"""
	if not doc.get("loyalty_program") and not doc.get("redeem_loyalty_points"):
		return

	if not doc.get("pos_profile"):
		return

	from restaurant_pos.utils.terminal_branch import is_till

	if not is_till(doc.pos_profile):
		return

	doc.loyalty_program = None
	doc.redeem_loyalty_points = 0


def eligible(order):
	"""The program this bill earns and spends in, or None. Writes nothing.

	Four ways a bill is outside the scheme, each a decision somebody made:

	- **No customer.** Points belong to a person, and a walk-in is nobody.
	- **The terminal's default customer** — the name every anonymous bill is
	  filed under. It is a customer record, and ERPNext's auto opt-in would
	  happily enrol it and let it collect points off every stranger.
	- **An order type with loyalty switched off** — a delivery platform's order is
	  the platform's customer, which is why Toast refuses those too.
	- **No program that takes this customer** — none set, none opting them in,
	  or one outside its dates or another company's.
	"""
	if not order.get("customer") or not order.get("pos_profile"):
		return None

	profile = frappe.get_cached_value("POS Profile", order.pos_profile, ["customer", "company"], as_dict=True)
	if not profile or order.customer == profile.customer:
		return None

	kind = frappe.get_cached_value(
		"Restaurant Order Type", order.order_type, ["allows_loyalty", "counterparty"], as_dict=True
	)
	# **An account order is never a member's purchase.** It is somebody else's
	# debt (`D-038`) — a delivery platform's guest, or a company billed monthly —
	# and a rule, not a switch: the migrate that added `allows_loyalty` set it on
	# every existing type, HungerStation and Jahez among them, and a switch a
	# manager has to remember to turn off is a switch that stays on.
	if not kind or not kind.allows_loyalty or kind.counterparty == "account":
		return None

	name = _program_name(order.customer)
	if not name:
		return None

	program = frappe.get_cached_doc("Loyalty Program", name)
	on = getdate(today())
	if program.company and program.company != profile.company:
		return None
	if getdate(program.from_date) > on or (program.to_date and getdate(program.to_date) < on):
		return None

	return program


def _program_name(customer: str) -> str | None:
	"""The customer's program, or the one ERPNext would enrol them in.

	ERPNext enrols on **saving the customer**, so a regular created before the
	program existed is in nothing until somebody edits them. Asking ERPNext's own
	rule — auto opt-in, customer group, territory, dates — answers for them
	without waiting; :func:`settle` writes the answer down on the first sale.
	"""
	name = frappe.db.get_value("Customer", customer, "loyalty_program")
	if name:
		return name

	from erpnext.selling.doctype.customer.customer import get_loyalty_programs

	found = get_loyalty_programs(frappe.get_doc("Customer", customer))
	# Two programs both claiming the customer is a configuration question, and
	# ERPNext itself asks a human rather than choosing. So does this.
	return found[0] if len(found) == 1 else None


def _earn_rate(program) -> float:
	"""Money spent per point earned — ERPNext's `collection_factor`."""
	return flt(program.collection_rules[0].collection_factor)


def minimum(program) -> int:
	"""The balance a customer must hold before any of it can be spent."""
	return cint(program.get("rpos_min_redeem_points"))


def value_of(points: int, program) -> float:
	return flt(cint(points) * flt(program.conversion_factor), 2)


# --------------------------------------------------------------------------- #
# The balance
# --------------------------------------------------------------------------- #


def balances(on=None, *, company=None, customer=None, program=None) -> list:
	"""Points held on a day, per customer and program — the ledger's one sum.

	Every row posted by that day and not yet expired on it. Right because of the
	ledger's one rule: a movement carries its grant's expiry, so when a grant
	lapses its spending and its clawbacks lapse with it and the sum stays true.
	And a movement posted after the day does not count, so the last day of a
	month reads what stood that night, whatever was spent since — the figure an
	accountant closes the month on (`docs/12_Loyalty_Points.md` §5.3).

	The till asks for one customer today; the balance report for everyone on a
	chosen day. One query for both, so the two cannot disagree (`D-196`).
	"""
	on = getdate(on or today())
	entry = frappe.qb.DocType(LEDGER)
	query = (
		frappe.qb.from_(entry)
		.select(entry.customer, entry.loyalty_program, Sum(entry.loyalty_points).as_("points"))
		.where((entry.posting_date <= on) & (entry.expiry_date >= on))
		.groupby(entry.customer, entry.loyalty_program)
	)
	if company:
		query = query.where(entry.company == company)
	if customer:
		query = query.where(entry.customer == customer)
	if program:
		query = query.where(entry.loyalty_program == program)

	return query.run(as_dict=True)


def balance(customer: str, program: str) -> int:
	"""Points the customer can spend today.

	**It can be negative.** A return claws back points the bill earned even when
	they were already spent, and the debt is recovered from the next purchases
	rather than refusing the refund (`D-189`).
	"""
	rows = balances(customer=customer, program=program)
	return cint(rows[0].points) if rows else 0


def _most_points(program, have: int, before_points: float) -> int:
	"""The most points this bill can take right now.

	Nothing below the minimum balance. Otherwise the smaller of what the customer
	holds and what fits under the program's share of the bill — that share taken
	of what is left **after** the shop's own reductions, because points are spent
	on what the customer would actually pay.
	"""
	if have <= 0 or have < minimum(program):
		return 0

	percent = flt(program.get("rpos_max_redeem_percent")) or 100
	ceiling = max(0.0, flt(before_points)) * percent / 100
	fits = math.floor(ceiling / flt(program.conversion_factor) + _NOISE)

	return max(0, min(have, fits))


def on_the_bill(order) -> dict:
	"""What a screen needs to say about points on this bill (`FR-10.5`, `BR-082`).

	One shape, spread into the payment summary and the preview, the way
	`promotions.on_the_bill` is (§5.5). ``loyalty`` is ``None`` when the bill is
	outside the scheme, and the screen then says nothing: a hint about points
	on a walk-in's coffee is noise.

	``max_points`` is worked out on the bill **as it stands now** — after the
	discount and the offer the cashier is looking at — so the button offers
	exactly what the server will accept (`D-125`).
	"""
	spent = flt(order.get("loyalty_amount"))
	shape = {
		"loyalty_points": cint(order.get("loyalty_points")),
		"loyalty_amount": spent,
		"loyalty": None,
	}

	program = eligible(order)
	if not program:
		return shape

	have = balance(order.customer, program.name)
	# What the bill came to before the points took their share: the stored
	# discount folds all three reductions, so the points are added back.
	before_points = flt(order.subtotal) - flt(order.discount_amount) + spent

	most = _most_points(program, have, before_points)
	shape["loyalty"] = {
		"balance": have,
		"worth": value_of(have, program),
		"point_value": flt(program.conversion_factor),
		"min_points": minimum(program),
		"max_points": most,
		# What the button would take off — sent, so the screen shows money it did
		# not work out (`CLAUDE.md` §5.1).
		"max_amount": value_of(most, program),
	}
	return shape


# --------------------------------------------------------------------------- #
# On the bill
# --------------------------------------------------------------------------- #


def amount_for(order, after_others: float) -> float:
	"""What the points being spent take off this bill (`totals.calculate`).

	Never more than is left after the shop's own reductions, so the three can
	never add up to more than the bill. Whether the customer may spend them at
	all is :func:`assert_redeemable`'s question, asked once at the payment.
	"""
	# `getattr`, not `.get`: this is on `totals.calculate`'s path, which is
	# also run on plain order-shaped objects that are not documents — the
	# suite's own stub among them, and it found this. Nothing below is reached
	# unless points are actually being spent, so `eligible` sees documents only.
	points = cint(getattr(order, "loyalty_points", 0))
	if points <= 0:
		return 0.0

	program = eligible(order)
	if not program:
		return 0.0

	return flt(min(value_of(points, program), max(0.0, flt(after_others))), 2)


def assert_redeemable(order) -> None:
	"""Refuse a redemption the customer cannot make (`FR-10.5`).

	Runs **inside the payment's transaction, with the customer locked**. Two tills
	spending the same balance at the same moment is the double spend, and a
	balance read without the lock is a balance that may already be gone.
	"""
	points = cint(order.get("loyalty_points"))
	if points <= 0:
		return

	program = eligible(order)
	if not program:
		frappe.throw(_("Loyalty points cannot be used on this bill."))

	frappe.db.get_value("Customer", order.customer, "name", for_update=True)
	have = balance(order.customer, program.name)

	if have < minimum(program):
		frappe.throw(
			_("Points can be used from {0} upwards; this customer has {1}.").format(minimum(program), have)
		)

	if points > have:
		frappe.throw(_("This customer has {0} points.").format(have))

	before_points = flt(order.subtotal) - flt(order.discount_amount) + flt(order.loyalty_amount)
	most = _most_points(program, have, before_points)
	if points > most:
		frappe.throw(_("At most {0} points can be used on this bill.").format(most))


# --------------------------------------------------------------------------- #
# At the payment
# --------------------------------------------------------------------------- #


def settle(order, invoice) -> dict:
	"""Spend what the bill used and grant what it earned, once it is invoiced.

	**Earned on the invoice's `net_total`** — before VAT and after every
	reduction, the points included — so nothing is earned on the tax (Starbucks
	Saudi excludes it in the same words) and nothing on the part the points paid
	for (`BR-084`). Floored per bill: a fraction of a point is not a point.
	"""
	program = eligible(order)
	if not program:
		return {}

	_enrol(order.customer, program.name)

	spent = cint(order.get("loyalty_points"))
	if spent:
		before = balance(order.customer, program.name)
		_spend(order.customer, program, spent, invoice)
		_story_and_audit(order, invoice, spent, before)

	basis = flt(invoice.net_total)
	earned = math.floor(basis / _earn_rate(program) + _NOISE) if basis > 0 else 0
	if earned > 0:
		_grant(
			customer=order.customer,
			program=program,
			points=earned,
			invoice=invoice,
			basis=basis,
			expires=add_days(invoice.posting_date, cint(program.expiry_duration)),
		)
		_log_activity(order, "loyalty_earned", f"+{earned}", {"points": earned, "on": basis})

	order.loyalty_points_earned = earned
	return {"loyalty_points_earned": earned, "loyalty_balance": balance(order.customer, program.name)}


def _enrol(customer: str, program: str) -> None:
	"""Write down the program :func:`_program_name` inferred, on the first sale."""
	if not frappe.db.get_value("Customer", customer, "loyalty_program"):
		frappe.db.set_value("Customer", customer, "loyalty_program", program, update_modified=False)


def _spend(customer: str, program, points: int, invoice) -> None:
	"""Take `points` from the grants that expire soonest (`D-189`)."""
	for grant, free in _spendable(customer, program.name):
		take = min(free, points)
		_move(grant, -take, invoice)
		points -= take
		if points <= 0:
			return

	# `assert_redeemable` checked the balance under the lock, and the balance is
	# the sum of exactly these grants — so arriving here is a ledger that does
	# not add up, and posting a bill against it would hide that.
	frappe.throw(_("The loyalty balance changed while this bill was being paid. Nothing has been charged."))


def _spendable(customer: str, program: str) -> list[tuple]:
	"""Unexpired grants with points left on them, soonest to expire first."""
	grants = frappe.get_all(
		LEDGER,
		filters={
			"customer": customer,
			"loyalty_program": program,
			"redeem_against": ("is", "not set"),
			"loyalty_points": (">", 0),
			"expiry_date": (">=", getdate(today())),
		},
		fields=["name", "loyalty_points", "expiry_date", "loyalty_program_tier", "company"],
		order_by="expiry_date asc, creation asc",
	)
	if not grants:
		return []

	entry = frappe.qb.DocType(LEDGER)
	used = dict(
		(
			frappe.qb.from_(entry)
			.select(entry.redeem_against, Sum(entry.loyalty_points))
			.where(entry.redeem_against.isin([grant.name for grant in grants]))
			.groupby(entry.redeem_against)
		).run()
	)

	return [
		(grant, cint(grant.loyalty_points) + cint(used.get(grant.name)))
		for grant in grants
		if cint(grant.loyalty_points) + cint(used.get(grant.name)) > 0
	]


def _grant(*, customer: str, program, points: int, invoice, basis: float, expires) -> None:
	frappe.get_doc(
		{
			"doctype": LEDGER,
			"company": invoice.company,
			"loyalty_program": program.name,
			"loyalty_program_tier": program.collection_rules[0].tier_name,
			"customer": customer,
			"invoice_type": SALE,
			"invoice": invoice.name,
			"loyalty_points": points,
			# ERPNext reads this as "spent" when it works out a tier. Only a real
			# purchase carries one; a restored grant or a movement carries zero, or
			# the same riyals would be counted twice.
			"purchase_amount": basis,
			"expiry_date": expires,
			"posting_date": invoice.posting_date,
		}
	).insert(ignore_permissions=True)


def _move(grant, points: int, invoice) -> None:
	"""A movement against one grant — spending, or a clawback — expiring with it."""
	frappe.get_doc(
		{
			"doctype": LEDGER,
			"company": grant.company,
			"loyalty_program": grant.loyalty_program
			or frappe.db.get_value(LEDGER, grant.name, "loyalty_program"),
			"loyalty_program_tier": grant.loyalty_program_tier,
			"customer": grant.customer or frappe.db.get_value(LEDGER, grant.name, "customer"),
			"invoice_type": SALE,
			"invoice": invoice.name,
			"redeem_against": grant.name,
			"loyalty_points": points,
			"purchase_amount": 0,
			"expiry_date": grant.expiry_date,
			"posting_date": invoice.posting_date,
		}
	).insert(ignore_permissions=True)


def _story_and_audit(order, invoice, points: int, before: int) -> None:
	"""A redemption is on the bill's story **and** in the audit log.

	The story because anything that happens to a bill is written on it. The
	audit log because spending a customer's balance is the one loyalty act a
	cashier can abuse — their own number instead of the guest's is the fraud
	every loyalty vendor warns about — and a manager looking for it reads there.
	"""
	from restaurant_pos.utils.audit import log_audit

	amount = flt(order.get("loyalty_amount"))
	details = {
		"customer": order.customer,
		"points": points,
		"amount": amount,
		"balance_before": before,
		"sales_invoice": invoice.name,
	}

	audit = log_audit(
		"loyalty_redeemed",
		branch=order.branch,
		pos_profile=order.pos_profile,
		restaurant_order=order.name,
		details=details,
	)
	_log_activity(order, "loyalty_redeemed", f"{points} = {amount:.2f}", details, audit_log=audit)


def _log_activity(order, action: str, subject: str, details: dict, audit_log: str | None = None) -> None:
	from restaurant_pos.utils import activity

	activity.log(order, action, subject=subject, details=details, audit_log=audit_log)


# --------------------------------------------------------------------------- #
# On a return
# --------------------------------------------------------------------------- #


def reverse(order, credit, *, completes: bool) -> dict:
	"""Take back what the returned share earned, and give back what it spent.

	**Proportional to what came back**, measured on the lines before any
	reduction — the same measure the refund's own share of the discount uses —
	and exactly all of it once nothing is left to return (`completes`), so a bill
	returned in three parts ends where one returned whole does.

	Worked **cumulatively**: each return computes where the bill should stand
	after every return so far and writes only the difference. Rounding cannot
	pile up across parts, and a return that changes nothing writes nothing.

	**The earned points come back even when they were spent.** The balance goes
	negative and the next purchases pay it off; refusing the refund over it — as
	ERPNext does — leaves a cashier with money in hand and no way to give it.
	"""
	sale = credit.return_against
	grant = frappe.db.get_value(
		LEDGER,
		{"invoice": sale, "redeem_against": ("is", "not set"), "loyalty_points": (">", 0)},
		[
			"name",
			"customer",
			"loyalty_program",
			"loyalty_program_tier",
			"company",
			"loyalty_points",
			"expiry_date",
		],
		as_dict=True,
	)
	spent = frappe.get_all(
		LEDGER,
		filters={"invoice": sale, "loyalty_points": ("<", 0)},
		fields=["customer", "loyalty_program", "loyalty_points", "expiry_date", "company"],
	)
	if not grant and not spent:
		return {}

	notes = frappe.get_all(SALE, filters={"return_against": sale, "docstatus": 1}, pluck="name")
	share = 1.0 if completes else _share_returned(sale, notes)
	result = {}

	if grant:
		back = _movements(notes, redeem_against=grant.name)
		keep = math.floor(cint(grant.loyalty_points) * (1 - share) + _NOISE)
		change = keep - (cint(grant.loyalty_points) + back)
		if change < 0:
			_move(grant, change, credit)
			_log_activity(
				order, "loyalty_clawed_back", str(change), {"points": change, "credit_note": credit.name}
			)
			result["loyalty_points_clawed_back"] = -change

	if spent:
		total = -sum(cint(row.loyalty_points) for row in spent)
		owed = math.floor(total * share + _NOISE)
		change = owed - _movements(notes, restored=True)
		if change > 0:
			first = spent[0]
			program = frappe.get_cached_doc("Loyalty Program", first.loyalty_program)
			# Back with the date they had, not a fresh one: a return is not a
			# purchase, and a new expiry would let a return extend old points.
			_grant(
				customer=first.customer,
				program=program,
				points=change,
				invoice=credit,
				basis=0,
				expires=max(getdate(row.expiry_date) for row in spent),
			)
			_log_activity(
				order, "loyalty_restored", f"+{change}", {"points": change, "credit_note": credit.name}
			)
			result["loyalty_points_restored"] = change

	return result


def _share_returned(sale: str, notes: list[str]) -> float:
	"""How much of the bill has come back so far, by the value of its lines."""
	whole = flt(frappe.db.get_value(SALE, sale, "total"))
	if not whole or not notes:
		return 0.0

	back = sum(
		abs(flt(total)) for total in frappe.get_all(SALE, filters={"name": ("in", notes)}, pluck="total")
	)
	return min(1.0, back / whole)


def _movements(notes: list[str], *, redeem_against: str | None = None, restored: bool = False) -> int:
	"""Points the bill's credit notes have already moved, of one kind."""
	if not notes:
		return 0

	filters = {"invoice": ("in", notes)}
	if restored:
		filters.update({"redeem_against": ("is", "not set"), "loyalty_points": (">", 0)})
	else:
		filters["redeem_against"] = redeem_against

	return sum(cint(points) for points in frappe.get_all(LEDGER, filters=filters, pluck="loyalty_points"))

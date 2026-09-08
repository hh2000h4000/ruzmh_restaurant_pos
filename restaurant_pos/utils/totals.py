# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Money for a Restaurant Order.

Every amount is computed here and nowhere else. The Vue app displays what this
returns and never calculates (``CLAUDE.md`` §5.1).

Order of operations is fixed by ``FR-10.4``: the discount applies to the pre-tax
subtotal, then VAT is recalculated on the discounted net. Applying the discount
after tax would under-collect VAT.

The order total is **operational**. The financial truth is the Sales Invoice,
whose taxes ERPNext computes at payment time (``DECISIONS.md`` D-018).

Refs: FR-10.4, BR-024, CLAUDE.md §5.1
"""

import frappe
from frappe import _
from frappe.utils import flt, round_based_on_smallest_currency_fraction

CURRENCY_PRECISION = 2

#: BR-024. Stored on the ERPNext ``Currency`` record, not here, so the order
#: screen and the Sales Invoice can never disagree — see :func:`round_to_step`.
DEFAULT_CURRENCY = "SAR"
SAUDI_ROUNDING_STEP = 0.05


def round_to_step(amount, currency: str = DEFAULT_CURRENCY) -> float:
	"""Apply the currency's cash rounding step (BR-024).

	Delegates to the same Frappe helper ERPNext uses for ``rounded_total``, and
	reads the same ``Currency.smallest_currency_fraction_value``. Rolling our own
	0.05 rounding here would have quietly disagreed with the invoice: the field
	ships as ``0`` for SAR, which makes ERPNext round to whole riyals. The
	restaurant would have shown one figure and charged another.

	``setup/defaults.py`` sets the field to 0.05 on install.
	"""
	return round_based_on_smallest_currency_fraction(flt(amount), currency, CURRENCY_PRECISION)


def money(amount) -> float:
	return flt(amount, CURRENCY_PRECISION)


def rounding_step(currency: str = DEFAULT_CURRENCY) -> float:
	"""The currency's cash rounding step (BR-024) — 0.05 for SAR.

	Read here rather than in each caller so `pricing_inputs`, which ships it to
	an offline device, and :func:`split_evenly`, which divides by it, cannot end
	up reading two different fields one day.

	Cached: it is read once per priced order and once per share of a split bill,
	and a currency's rounding step changes about never.
	"""
	return flt(frappe.get_cached_value("Currency", currency, "smallest_currency_fraction_value"))


def split_evenly(total, ways: int, currency: str = DEFAULT_CURRENCY) -> list[float]:
	"""Divide a bill into `ways` shares that add back up to it **exactly**.

	The obvious version is wrong, and wrong in a way nobody notices until the
	drawer is counted: 100.00 over three is 33.3333, and rounding each share to
	the 0.05 the riyal is settled in gives 33.35 three times — 100.05. Five
	halalas the restaurant charged, never billed, and cannot bank. Rounding
	down instead loses money on every split bill in the other direction.

	So the arithmetic is done in **whole rounding steps** rather than in riyals.
	The bill is a whole number of 0.05s; that number is divided by `ways`, and
	the shares that cannot be equal differ by exactly one step. The sum is the
	bill by construction, not by luck.

	The odd steps go to the **first** shares. Somebody has to pay the extra
	five halalas, and the person tendering first is the one standing there.

	Refs: BR-024, FR-10.1
	"""
	ways = int(ways or 0)
	if ways < 1:
		frappe.throw(_("A bill is split between one person or more."))

	# A currency with no step configured is settled to the last decimal place,
	# so that is its step. Never zero: this divides by it.
	step = rounding_step(currency) or 10**-CURRENCY_PRECISION

	units = round(flt(total) / step)
	base, extra = divmod(units, ways)

	return [money((base + (1 if index < extra else 0)) * step) for index in range(ways)]


def _tax_rows(pos_profile: str) -> list:
	"""The proportional rows of the POS Profile's ERPNext tax template.

	Only ``On Net Total`` rows can be applied to a running order total. Anything
	else — an actual amount, a charge on a previous row — belongs to the Sales
	Invoice, which ERPNext computes properly at payment.
	"""
	template = frappe.db.get_value("POS Profile", pos_profile, "taxes_and_charges")
	if not template:
		return []

	rows = frappe.get_all(
		"Sales Taxes and Charges",
		filters={"parent": template, "parenttype": "Sales Taxes and Charges Template"},
		fields=["charge_type", "rate", "included_in_print_rate"],
	)
	return [row for row in rows if row.charge_type == "On Net Total"]


def tax_rate_for(pos_profile: str) -> float:
	"""Tax rate from the POS Profile's ERPNext tax template.

	Never hardcoded. A restaurant outside KSA, or a zero-rated outlet, is a
	configuration change and not a code change (``CLAUDE.md`` §5.1).
	"""
	return sum(flt(row.rate) for row in _tax_rows(pos_profile))


def tax_is_inclusive(pos_profile: str) -> bool:
	"""Whether the menu price already contains the tax (`D-091`).

	ERPNext's own flag, `included_in_print_rate`, read rather than guessed —
	VAT-inclusive display prices are the Saudi norm, and which way round it is
	changes what the till may quote before an invoice exists.

	A template that mixes inclusive and exclusive rows has no single answer, and
	the running total on the order screen needs one. Any inclusive row makes the
	bill inclusive; ERPNext still computes the invoice row by row, and the
	comparison at payment would catch a template built that way.
	"""
	return any(row.included_in_print_rate for row in _tax_rows(pos_profile))


def discount_amount(subtotal: float, discount_type: str | None, discount_value: float) -> float:
	"""The money taken off, from either a percentage or a flat amount."""
	if not discount_type or not discount_value:
		return 0.0

	if discount_type == "percentage":
		if not 0 <= flt(discount_value) <= 100:
			frappe.throw(_("A percentage discount must be between 0 and 100."))
		return money(flt(subtotal) * flt(discount_value) / 100)

	return money(min(flt(discount_value), flt(subtotal)))


def line_amount(rate: float, qty: float, modifier_delta: float = 0.0) -> float:
	"""One order line, including the price effect of its modifiers."""
	return money((flt(rate) + flt(modifier_delta)) * flt(qty))


def pricing_inputs(pos_profile: str) -> dict:
	"""Everything a device needs to reach the same total this module does (D-071).

	Three settings live on the server and nowhere else: the tax rate on the POS
	Profile's template, the cash-rounding step on the ERPNext `Currency`, and the
	rounding method in System Settings. A till that guessed any of them would
	quote a customer one figure while the invoice carried another — which is the
	whole reason `CLAUDE.md` §5.1 says the backend computes.

	It still does. **This ships the inputs, not the authority**: the device
	applies them while the connection is down, and the server recomputes on sync
	and reports any difference rather than swallowing it (`09` §5).
	"""
	currency = frappe.db.get_value("POS Profile", pos_profile, "currency") or DEFAULT_CURRENCY

	return {
		"currency": currency,
		"precision": CURRENCY_PRECISION,
		"tax_rate": tax_rate_for(pos_profile),
		"tax_inclusive": 1 if tax_is_inclusive(pos_profile) else 0,
		"rounding_step": rounding_step(currency),
		"rounding_method": frappe.get_system_settings("rounding_method") or "Banker's Rounding (legacy)",
	}


def compute(line_amounts: list, discount_type: str | None, discount_value, pricing: dict) -> dict:
	"""The arithmetic itself, with nothing to look up (D-071).

	Pulled out of :func:`calculate` so there is exactly **one** description of
	how a bill adds up, and the device's port has a single function to mirror.
	A second path here — one for the order, one for the offline copy — is how
	two figures for one meal are born.
	"""
	subtotal = money(sum(flt(amount) for amount in line_amounts))
	discount = discount_amount(subtotal, discount_type, discount_value)
	rate = flt(pricing["tax_rate"])
	after_discount = money(subtotal - discount)

	if pricing.get("tax_inclusive"):
		# The menu price already contains the tax, so the figure the customer
		# was quoted *is* the total and the tax is extracted from it rather than
		# added to it (`D-091`). `subtotal` stays the sum of the menu prices —
		# it is what the cashier and the customer are both looking at.
		net = money(after_discount / (1 + rate / 100)) if rate else after_discount
		tax = money(after_discount - net)
		total = after_discount
	else:
		net = after_discount
		tax = money(net * rate / 100)
		total = money(net + tax)

	return {
		"subtotal": subtotal,
		"discount_amount": discount,
		"tax_amount": tax,
		"total_amount": round_to_step(total, pricing["currency"]),
	}


def calculate(order) -> None:
	"""Recompute every total on ``order`` in place.

	Voided lines are excluded: BR-013 removes a voided item from the order
	total while keeping the row for the audit trail.

	**The promotion is folded in here, not inside `compute`** (`D-163`). That
	function is the one description of how a bill adds up and the device mirrors
	it line for line while the connection is down (`D-071`), under a contract in
	`shared/totals_contract.json`. Adding a term to it would mean the offline
	port had to evaluate promotions too — which it cannot: the rules live in the
	database. So the promotion is resolved to **an amount off** first, and the
	arithmetic below is the same arithmetic it always was.

	An offline bill therefore carries no promotion, and the server recomputes on
	sync and reports the difference rather than swallowing it (`09` §5).
	"""
	amounts = [flt(row.amount) for row in (order.items or []) if row.status != "void"]
	pricing = pricing_inputs(order.pos_profile)

	subtotal = money(sum(flt(amount) for amount in amounts))
	manual = discount_amount(subtotal, order.discount_type, order.discount_value)
	promotion, promoted = _promotion_for(order, subtotal - manual)

	order.promotion = promotion
	order.promotion_amount = promoted

	# One reduction from here down, so `compute` keeps the single shape the
	# offline port mirrors. What each half of it was is on the order above.
	totals = compute(amounts, "amount", manual + promoted, pricing)

	order.subtotal = totals["subtotal"]
	order.discount_amount = totals["discount_amount"]
	order.tax_amount = totals["tax_amount"]
	order.total_amount = totals["total_amount"]


def _promotion_for(order, after_manual: float) -> tuple[str | None, float]:
	"""The promotion this bill qualifies for, and what it takes off (`FR-11.2`).

	Never more than what is left after a person's own discount: two reductions
	that together exceed the bill would hand money back, and the cashier would
	find out at the payment screen.

	A promotion is **never** allowed to fail a sale. The rules are configuration,
	and configuration that is half-written is somebody's Tuesday afternoon — not
	a reason a customer cannot pay. So a broken rule is logged and the bill is
	rung up without it.
	"""
	# Lazy: `promotions` reads the order's items, and this module is imported by
	# nearly everything that touches one.
	from restaurant_pos.utils import promotions

	try:
		chosen = promotions.best_for(order, total=after_manual)
	except Exception:
		frappe.log_error("Promotion evaluation failed", "RPOS promotions")
		return None, 0.0

	if not chosen:
		return None, 0.0

	return chosen.name, flt(min(flt(chosen.benefit), max(0.0, after_manual)), 2)

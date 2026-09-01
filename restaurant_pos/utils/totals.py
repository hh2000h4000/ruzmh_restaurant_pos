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
		"rounding_step": flt(frappe.db.get_value("Currency", currency, "smallest_currency_fraction_value")),
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
	"""
	amounts = [flt(row.amount) for row in (order.items or []) if row.status != "void"]

	totals = compute(amounts, order.discount_type, order.discount_value, pricing_inputs(order.pos_profile))

	order.subtotal = totals["subtotal"]
	order.discount_amount = totals["discount_amount"]
	order.tax_amount = totals["tax_amount"]
	order.total_amount = totals["total_amount"]

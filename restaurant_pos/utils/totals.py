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


def tax_rate_for(pos_profile: str) -> float:
	"""Net-total tax rate from the POS Profile's ERPNext tax template.

	Never hardcoded. A restaurant outside KSA, or a zero-rated outlet, is a
	configuration change and not a code change (``CLAUDE.md`` §5.1).
	"""
	template = frappe.db.get_value("POS Profile", pos_profile, "taxes_and_charges")
	if not template:
		return 0.0

	rows = frappe.get_all(
		"Sales Taxes and Charges",
		filters={"parent": template, "parenttype": "Sales Taxes and Charges Template"},
		fields=["charge_type", "rate"],
	)

	# Only proportional-on-net rows can be applied to a running order total.
	# Anything else (actual amounts, on-previous-row) belongs to the Sales
	# Invoice, which ERPNext computes properly at payment.
	return sum(flt(row.rate) for row in rows if row.charge_type == "On Net Total")


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


def calculate(order) -> None:
	"""Recompute every total on ``order`` in place.

	Voided lines are excluded: BR-013 removes a voided item from the order
	total while keeping the row for the audit trail.
	"""
	subtotal = sum(flt(row.amount) for row in (order.items or []) if row.status != "void")
	order.subtotal = money(subtotal)

	order.discount_amount = discount_amount(order.subtotal, order.discount_type, order.discount_value)

	net = money(order.subtotal - order.discount_amount)
	rate = tax_rate_for(order.pos_profile)

	order.tax_amount = money(net * rate / 100)

	currency = frappe.db.get_value("POS Profile", order.pos_profile, "currency") or DEFAULT_CURRENCY
	order.total_amount = round_to_step(net + order.tax_amount, currency)

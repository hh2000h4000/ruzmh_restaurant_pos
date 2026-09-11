# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The points the restaurant owes on a day — the figure a month-end entry is made from.

A point earned is a discount promised and not yet given. Under SOCPA's IFRS for
SMEs (23A.9) the share of a sale that paid for it is a liability until the point
is spent or expires, and RPOS records every point, so the exemption for shops
that cannot does not apply (`docs/12_Loyalty_Points.md` §5.2). The accountant
adjusts the liability each month by the difference (§5.3); this is the number:
the unspent, unexpired points at the point's value, net of VAT, times the share
the accountant expects to be spent.

**The balance is the till's own sum**, :func:`loyalty.balances`, not a second
query — so the report and the screen cannot disagree about a customer.

**The share is the accountant's**, so it is a filter, not a constant.

**A negative balance is not an asset.** A return claws back points the bill
earned even after they were spent, and the customer carries the debt into their
next purchases (`D-189`). Nobody can be billed for it, so it is listed and kept
out of the liability.

Refs: BR-080, D-189, D-196
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, today

from restaurant_pos.utils import loyalty, totals


def execute(filters=None):
	filters = frappe._dict(filters or {})
	company = filters.company or frappe.defaults.get_user_default("Company")
	if not company:
		frappe.throw(_("Choose the company to report on."))

	on = getdate(filters.on or today())
	share = 100.0 if filters.expected_redemption in (None, "") else flt(filters.expected_redemption)
	currency = frappe.get_cached_value("Company", company, "default_currency")

	vat = _vat(company)
	divisor = (1 + vat[0] / 100 if vat[1] else 1.0) if vat else None

	rows = [
		row
		for row in loyalty.balances(
			on, company=company, customer=filters.customer, program=filters.loyalty_program
		)
		if cint(row.points)
	]
	programs = {
		program.name: program
		for program in frappe.get_all("Loyalty Program", fields=["name", "conversion_factor"])
	}
	names = (
		dict(
			frappe.get_all(
				"Customer",
				filters={"name": ("in", [row.customer for row in rows])},
				fields=["name", "customer_name"],
				as_list=True,
			)
		)
		if rows
		else {}
	)

	data = []
	for row in sorted(rows, key=lambda row: cint(row.points), reverse=True):
		value = loyalty.value_of(row.points, programs[row.loyalty_program])
		data.append(
			{
				"customer": row.customer,
				"customer_name": names.get(row.customer),
				"loyalty_program": row.loyalty_program,
				"points": cint(row.points),
				"value": value,
				"net": flt(value / divisor, 2) if divisor else None,
				"currency": currency,
			}
		)

	return _columns(), data, _message(vat), None, _summary(data, divisor, share, currency)


def _vat(company: str) -> tuple[float, bool] | None:
	"""The VAT points are spent under: rate, and whether the menu includes it.

	Read from the tax template on the company's terminals — never a constant
	(`CLAUDE.md` §5.1). With VAT-inclusive menus (`D-091`) five riyals of points
	are 4.35 of revenue and 0.65 of VAT; with exclusive prices the points come
	off before the tax, and the whole five is revenue.

	A terminal with no template says nothing about the rate. Two templates that
	disagree leave it unknown — ``None`` — and the report says so rather than
	picking one.
	"""
	terminals = frappe.get_all(
		"POS Profile",
		filters={"company": company, "disabled": 0, "taxes_and_charges": ("is", "set")},
		pluck="name",
	)
	bases = {(totals.tax_rate_for(name), totals.tax_is_inclusive(name)) for name in terminals}
	if len(bases) > 1:
		return None
	return bases.pop() if bases else (0.0, False)


def _message(vat) -> str:
	if vat is None:
		return _(
			"This company's terminals sell under tax templates that disagree, so the net and the "
			"liability are left out. Work them from the value."
		)
	rate, inclusive = vat
	if not rate:
		return _("These terminals charge no VAT, so the net is the value itself.")
	if inclusive:
		return _(
			"Net of VAT at {0}%, which the menu prices include, from the terminals' tax template."
		).format(f"{rate:g}")
	return _("Points come off before VAT on these terminals, so the net is the value itself.")


def _summary(data: list[dict], divisor: float | None, share: float, currency: str) -> list[dict]:
	held = [row for row in data if row["points"] > 0]
	owed = -sum(row["points"] for row in data if row["points"] < 0)
	value = flt(sum(row["value"] for row in held), 2)

	summary = [
		{"label": _("Points held"), "value": sum(row["points"] for row in held), "datatype": "Int"},
		{"label": _("Their value"), "value": value, "datatype": "Currency", "currency": currency},
	]
	if divisor:
		net = flt(value / divisor, 2)
		summary += [
			{"label": _("Net of VAT"), "value": net, "datatype": "Currency", "currency": currency},
			{
				"label": _("Liability at {0}% expected to be spent").format(f"{share:g}"),
				"value": flt(net * share / 100, 2),
				"datatype": "Currency",
				"currency": currency,
				"indicator": "Red",
			},
		]
	if owed:
		summary.append(
			{
				"label": _("Points owed back by customers"),
				"value": owed,
				"datatype": "Int",
				"indicator": "Grey",
			}
		)
	return summary


def _columns() -> list[dict]:
	return [
		{
			"fieldname": "customer",
			"label": _("Customer"),
			"fieldtype": "Link",
			"options": "Customer",
			"width": 170,
		},
		{"fieldname": "customer_name", "label": _("Customer Name"), "fieldtype": "Data", "width": 190},
		{
			"fieldname": "loyalty_program",
			"label": _("Loyalty Program"),
			"fieldtype": "Link",
			"options": "Loyalty Program",
			"width": 160,
		},
		{"fieldname": "points", "label": _("Points"), "fieldtype": "Int", "width": 110},
		{
			"fieldname": "value",
			"label": _("Value"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
		{
			"fieldname": "net",
			"label": _("Net of VAT"),
			"fieldtype": "Currency",
			"options": "currency",
			"width": 130,
		},
	]

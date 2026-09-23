# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Which dishes sold, over a stretch of days — the report an owner reads weekly.

**ERPNext already has the register, and this is not it.** `Item-wise Sales
Register` prints one row per invoice line, over every invoice in the company,
with no notion of a branch or an order type — a thousand rows that answer "what
was on invoice 412", not "what does this restaurant sell". The question here is
the other one: one row per dish, ranked, with its share of the takings. Foodics
calls it the product mix and it is the first screen a restaurant owner opens.

**Amounts exclude VAT.** `net_amount` is the ex-tax figure whether the branch
prices tax-inclusive (`D-091`) or not, so the same column means the same thing
across branches, and it is the number a food cost is compared against.

**Dated the way money is dated everywhere else** (`D-217`): a sale counts in the
period its bill was settled, whatever day opened it, and a refund counts in the
period it was paid out, against a sale of any age. So this report and the day's
report cannot disagree about the same fortnight.

Refs: FR-11.2, D-217, D-243
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

#: A bill that took money. Cancelled ones sold nothing.
SETTLED = "closed"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date, to_date = _window(filters)

	sold = _sold_lines(filters, from_date, to_date)
	returned = _returned_lines(filters, from_date, to_date)

	rows = _tally(sold, returned, by_group=bool(filters.group_by_item_group))
	rows = [row for row in rows if row["qty"] or row["returned_qty"]]
	rows.sort(key=lambda row: row["amount"], reverse=True)

	total = sum(row["amount"] for row in rows)
	for row in rows:
		row["share"] = flt(row["amount"] / total * 100, 2) if total else 0.0

	return _columns(by_group=bool(filters.group_by_item_group)), rows


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #


def _window(filters) -> tuple[str, str]:
	if not filters.from_date or not filters.to_date:
		frappe.throw(_("Choose the days to report on."))

	from_date, to_date = getdate(filters.from_date), getdate(filters.to_date)
	if from_date > to_date:
		frappe.throw(_("From Date cannot be after To Date."))

	return f"{from_date} 00:00:00", f"{to_date} 23:59:59"


def _scope(filters) -> dict:
	"""The branch and order type, as filters on `Restaurant Order`."""
	scope = {}
	if filters.branch:
		scope["branch"] = filters.branch
	if filters.order_type:
		scope["order_type"] = filters.order_type
	return scope


# --------------------------------------------------------------------------- #
# Lines
# --------------------------------------------------------------------------- #


def _lines_of(invoices: list[str], item_group: str | None) -> list[frappe._dict]:
	if not invoices:
		return []

	filters = {"parent": ("in", invoices), "docstatus": 1}
	if item_group:
		filters["item_group"] = item_group

	return frappe.get_all(
		"Sales Invoice Item",
		filters=filters,
		fields=["item_code", "item_name", "item_group", "qty", "net_amount"],
	)


def _sold_lines(filters, from_date: str, to_date: str) -> list[frappe._dict]:
	invoices = frappe.get_all(
		"Restaurant Order",
		filters={
			**_scope(filters),
			"status": SETTLED,
			"closed_at": ("between", [from_date, to_date]),
			"sales_invoice": ("is", "set"),
		},
		pluck="sales_invoice",
	)
	return _lines_of(invoices, filters.item_group)


def _returned_lines(filters, from_date: str, to_date: str) -> list[frappe._dict]:
	"""Credit notes paid out in the window, against a sale of any age (`D-217`).

	Scoped through the bill they reverse, because a credit note carries no branch
	of its own — the same walk `utils/returns` makes to find a refund's order.
	"""
	credits = frappe.get_all(
		"Sales Invoice",
		filters={
			"is_return": 1,
			"docstatus": 1,
			"posting_date": ("between", [getdate(from_date), getdate(to_date)]),
			"return_against": ("is", "set"),
		},
		fields=["name", "return_against"],
	)
	if not credits:
		return []

	scope = _scope(filters)
	originals = list({row.return_against for row in credits})
	in_scope = set(
		frappe.get_all(
			"Restaurant Order",
			filters={**scope, "sales_invoice": ("in", originals)},
			pluck="sales_invoice",
		)
	)

	return _lines_of([row.name for row in credits if row.return_against in in_scope], filters.item_group)


# --------------------------------------------------------------------------- #
# Tally
# --------------------------------------------------------------------------- #


def _tally(sold: list, returned: list, *, by_group: bool) -> list[dict]:
	"""One row per dish, or per group when the manager asks the coarser question."""
	rows: dict[str, dict] = {}

	def row_for(line) -> dict:
		key = line.item_group if by_group else line.item_code
		return rows.setdefault(
			key or "",
			{
				"item_group": line.item_group,
				"qty": 0.0,
				"returned_qty": 0.0,
				"net_qty": 0.0,
				"amount": 0.0,
			}
			# `item_name` carries no column: Frappe's Link cell reads it from the row
			# and prints "CODE: Name", so a column of its own would repeat the words.
			| ({} if by_group else {"item_code": line.item_code, "item_name": line.item_name}),
		)

	for line in sold:
		row = row_for(line)
		row["qty"] += flt(line.qty)
		row["amount"] += flt(line.net_amount)

	# A credit note's own quantities and amounts are already negative, so the
	# returned column is their size and the takings simply add them.
	for line in returned:
		row = row_for(line)
		row["returned_qty"] += abs(flt(line.qty))
		row["amount"] += flt(line.net_amount)

	for row in rows.values():
		row["net_qty"] = row["qty"] - row["returned_qty"]
		row["amount"] = flt(row["amount"], 2)

	return list(rows.values())


# --------------------------------------------------------------------------- #
# Columns
# --------------------------------------------------------------------------- #


def _columns(*, by_group: bool) -> list[dict]:
	# The Link cell already prints "CODE: Name", so a name column beside it would
	# be the same words twice.
	item = {
		"fieldname": "item_code",
		"label": _("Item"),
		"fieldtype": "Link",
		"options": "Item",
		"width": 260,
	}
	group = {
		"fieldname": "item_group",
		"label": _("Item Group"),
		"fieldtype": "Link",
		"options": "Item Group",
		"width": 180,
	}

	return ([group] if by_group else [item, group]) + [
		{"fieldname": "qty", "label": _("Sold"), "fieldtype": "Float", "width": 90},
		{"fieldname": "returned_qty", "label": _("Returned"), "fieldtype": "Float", "width": 100},
		{"fieldname": "net_qty", "label": _("Net Quantity"), "fieldtype": "Float", "width": 110},
		{"fieldname": "amount", "label": _("Sales (excl. VAT)"), "fieldtype": "Currency", "width": 150},
		# **Float, not Percent.** Frappe's total row averages a percent column, and
		# the average of six dishes' shares is a number that means nothing. Summed,
		# the column totals 100 and says what it should.
		{"fieldname": "share", "label": _("Share of Sales %"), "fieldtype": "Float", "width": 130},
	]

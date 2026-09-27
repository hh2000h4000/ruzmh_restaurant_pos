# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Every bill of the period — a line a bill, or a line an item (`D-273`).

**Asked for by the user:** «a detailed sales report of the invoices by item, and
a summary by invoice». ERPNext has both — `Sales Register` and `Item-wise Sales
Register` — and neither says what a restaurant reads a bill by: the short daily
number the guest was called by, the order type, the table, the cashier who took
the money, and how it was paid.

**One report, one question** (`CLAUDE.md` §5.5): *what did we sell?* The two
views are the same bills at two depths, so they are a choice on the page rather
than two reports that could disagree on a total.

**And what came off each bill, and why** — the offer by name, the coupon that
unlocked it, the cashier's own discount and who approved it, and the points the
guest spent. Asked for by the user after a day of offers and coupons: the bill
said 0.00 and nothing on the register said how it got there. Read from the
order, which is where the reductions are kept apart (`D-163`, `D-189`); the
invoice holds only their sum.

**Refunds are on the page, negative**, on the day they were paid out (`D-217`),
each naming the bill it reverses — a register that shows only sales overstates
the period by everything handed back.

Refs: FR-11.2, D-217, D-273
"""

import frappe
from frappe import _
from frappe.utils import flt

from restaurant_pos.utils import reporting

ORDER_FIELDS = [
	"name",
	"daily_number",
	"order_type",
	"branch",
	"pos_profile",
	"table",
	"cashier",
	"customer",
	"closed_at",
	"sales_invoice",
	"discount_amount",
	"promotion",
	"promotion_amount",
	"coupon",
	"loyalty_amount",
	"discount_approved_by",
]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date, to_date = reporting.window(filters)

	orders = reporting.settled_orders(filters, from_date, to_date, ORDER_FIELDS)
	credits = reporting.credit_notes(filters, from_date, to_date)
	bills = _bills(orders, credits)
	if filters.discounted_only:
		bills = {name: bill for name, bill in bills.items() if bill["discount"]}

	if filters.view == "item":
		rows = _items(bills)
		return _item_columns(), ([*rows, _item_total(rows)] if rows else rows)

	rows = sorted(bills.values(), key=lambda row: str(row["at"]))
	return _invoice_columns(), ([*rows, _invoice_total(rows)] if rows else rows)


def _bills(orders: list, credits: list[str]) -> dict[str, dict]:
	"""Each invoice and credit note, with the order it came from."""
	by_invoice = {order.sales_invoice: order for order in orders}
	names = [*by_invoice, *credits]
	if not names:
		return {}

	invoices = {
		row.name: row
		for row in frappe.get_all(
			"Sales Invoice",
			filters={"name": ("in", names), "docstatus": 1},
			fields=[
				"name",
				"is_return",
				"return_against",
				"rpos_daily_number",
				"posting_date",
				"posting_time",
				"owner",
				"pos_profile",
				"customer",
				"net_total",
				"total_taxes_and_charges",
				"grand_total",
			],
		)
	}

	# A credit note has no order of its own: it borrows the one of the bill it
	# reverses, for the order type and the branch.
	missing = [row.return_against for row in invoices.values() if row.is_return]
	if missing:
		for order in frappe.get_all(
			"Restaurant Order", filters={"sales_invoice": ("in", missing)}, fields=ORDER_FIELDS
		):
			by_invoice.setdefault(order.sales_invoice, order)

	paid = _payments(list(invoices))
	names_of = _people(
		{order.cashier for order in orders}
		| {order.discount_approved_by for order in orders}
		| {row.owner for row in invoices.values()}
	)
	titles = _titles({order.order_type for order in by_invoice.values()})
	offers = _offers({order.promotion for order in orders})

	bills = {}
	for name, invoice in invoices.items():
		order = by_invoice.get(invoice.return_against if invoice.is_return else name) or frappe._dict()
		cashier = invoice.owner if invoice.is_return else order.cashier
		bills[name] = {
			"at": order.closed_at
			if not invoice.is_return
			else f"{invoice.posting_date} {invoice.posting_time}",
			"number": invoice.rpos_daily_number or order.daily_number,
			"invoice": name,
			"against": invoice.return_against if invoice.is_return else None,
			"order": order.name,
			"branch": order.branch,
			"order_type": titles.get(order.order_type, order.order_type),
			"table": order.table,
			# The till it was rung up on — a refund's own, where the money went out.
			"till": invoice.pos_profile or order.pos_profile,
			"cashier": names_of.get(cashier, cashier),
			"customer": invoice.customer,
			"sales": flt(invoice.net_total, 2),
			"tax": flt(invoice.total_taxes_and_charges, 2),
			"total": flt(invoice.grand_total, 2),
			"paid_by": paid.get(name, ""),
			**({} if invoice.is_return else _reductions(order, offers, names_of)),
		}
		bills[name].setdefault("discount", 0.0)
	return bills


def _reductions(order, offers: dict, names_of: dict) -> dict:
	"""The bill's one discount figure taken apart (`D-163`, `D-189`)."""
	offer = flt(order.promotion_amount)
	points = flt(order.loyalty_amount)
	manual = flt(flt(order.discount_amount) - offer - points, 2)
	return {
		"discount": flt(order.discount_amount, 2),
		"offer": offers.get(order.promotion, order.promotion) if offer else None,
		"coupon": order.coupon if offer else None,
		"offer_amount": flt(offer, 2),
		"manual_discount": manual if manual > 0 else 0.0,
		"approved_by": names_of.get(order.discount_approved_by, order.discount_approved_by)
		if manual > 0
		else None,
		"loyalty": flt(points, 2),
	}


def _offers(promotions: set) -> dict[str, str]:
	promotions = [name for name in promotions if name]
	if not promotions:
		return {}
	return {
		row.name: row.title_ar or row.title
		for row in frappe.get_all(
			"Restaurant Promotion",
			filters={"name": ("in", promotions)},
			fields=["name", "title", "title_ar"],
		)
	}


def _payments(invoices: list[str]) -> dict[str, str]:
	"""«Cash 30.00 · mada 23.00» for each invoice."""
	lines: dict[str, list[str]] = {}
	for row in frappe.get_all(
		"Sales Invoice Payment",
		filters={"parenttype": "Sales Invoice", "parent": ("in", invoices)},
		fields=["parent", "mode_of_payment", "amount"],
		order_by="idx asc",
	):
		if flt(row.amount):
			lines.setdefault(row.parent, []).append(f"{row.mode_of_payment} {flt(row.amount):.2f}")
	return {name: " · ".join(parts) for name, parts in lines.items()}


def _people(users: set) -> dict[str, str]:
	users = [user for user in users if user]
	if not users:
		return {}
	return dict(
		frappe.get_all("User", filters={"name": ("in", users)}, fields=["name", "full_name"], as_list=True)
	)


def _titles(order_types: set) -> dict[str, str]:
	order_types = [name for name in order_types if name]
	if not order_types:
		return {}
	return {
		row.name: row.title_ar or row.title
		for row in frappe.get_all(
			"Restaurant Order Type",
			filters={"name": ("in", order_types)},
			fields=["name", "title", "title_ar"],
		)
	}


def _items(bills: dict[str, dict]) -> list[dict]:
	"""Each line of each bill, carrying the bill's number, time and type."""
	if not bills:
		return []

	rows = []
	for line in frappe.get_all(
		"Sales Invoice Item",
		filters={"parenttype": "Sales Invoice", "parent": ("in", list(bills))},
		fields=["parent", "item_code", "item_name", "qty", "rate", "net_amount", "amount", "idx"],
		order_by="parent asc, idx asc",
	):
		bill = bills[line.parent]
		rows.append(
			{
				"at": bill["at"],
				"number": bill["number"],
				"invoice": line.parent,
				"order_type": bill["order_type"],
				"till": bill["till"],
				"item_code": line.item_code,
				"item_name": line.item_name,
				"qty": flt(line.qty),
				"rate": flt(line.rate, 2),
				"sales": flt(line.net_amount, 2),
				"amount": flt(line.amount, 2),
			}
		)
	return sorted(rows, key=lambda row: (str(row["at"]), row["invoice"]))


def _invoice_total(rows: list[dict]) -> dict:
	total = {
		"number": None,
		"invoice": _("Total", context="RPOS report"),
		"paid_by": _("{0} bills").format(len(rows)),
	}
	for field in ("sales", "tax", "total"):
		total[field] = flt(sum(row[field] for row in rows), 2)
	for field in ("discount", "offer_amount", "manual_discount", "loyalty"):
		total[field] = flt(sum(row.get(field) or 0 for row in rows), 2)
	return total


def _item_total(rows: list[dict]) -> dict:
	total = {"invoice": _("Total", context="RPOS report")}
	for field in ("qty", "sales", "amount"):
		total[field] = flt(sum(row[field] for row in rows), 2)
	return total


def _invoice_columns() -> list[dict]:
	return [
		{"fieldname": "at", "label": _("Time"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "number", "label": _("No."), "fieldtype": "Data", "width": 60},
		{
			"fieldname": "invoice",
			"label": _("Invoice"),
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"width": 150,
		},
		{
			"fieldname": "against",
			"label": _("Returns"),
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"width": 150,
		},
		{"fieldname": "order_type", "label": _("Order Type"), "fieldtype": "Data", "width": 110},
		{
			"fieldname": "table",
			"label": _("Table"),
			"fieldtype": "Link",
			"options": "Restaurant Table",
			"width": 90,
		},
		{
			"fieldname": "till",
			"label": _("Cashier Device"),
			"fieldtype": "Link",
			"options": "POS Profile",
			"width": 120,
		},
		{"fieldname": "cashier", "label": _("Cashier"), "fieldtype": "Data", "width": 130},
		{
			"fieldname": "customer",
			"label": _("Customer"),
			"fieldtype": "Link",
			"options": "Customer",
			"width": 130,
		},
		{"fieldname": "sales", "label": _("Sales before VAT"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "tax", "label": _("VAT"), "fieldtype": "Currency", "width": 90},
		{
			"fieldname": "total",
			"label": _("Total", context="RPOS report"),
			"fieldtype": "Currency",
			"width": 110,
		},
		{"fieldname": "paid_by", "label": _("Paid By"), "fieldtype": "Data", "width": 200},
		{"fieldname": "discount", "label": _("Total Discount"), "fieldtype": "Currency", "width": 110},
		{"fieldname": "offer", "label": _("Offer"), "fieldtype": "Data", "width": 150},
		{
			"fieldname": "coupon",
			"label": _("Coupon"),
			"fieldtype": "Link",
			"options": "POS Coupon",
			"width": 110,
		},
		{"fieldname": "offer_amount", "label": _("Offer Discount"), "fieldtype": "Currency", "width": 110},
		{
			"fieldname": "manual_discount",
			"label": _("Manual Discount"),
			"fieldtype": "Currency",
			"width": 110,
		},
		{"fieldname": "approved_by", "label": _("Approved By"), "fieldtype": "Data", "width": 130},
		{"fieldname": "loyalty", "label": _("Points Spent"), "fieldtype": "Currency", "width": 110},
	]


def _item_columns() -> list[dict]:
	return [
		{"fieldname": "at", "label": _("Time"), "fieldtype": "Datetime", "width": 150},
		{"fieldname": "number", "label": _("No."), "fieldtype": "Data", "width": 60},
		{
			"fieldname": "invoice",
			"label": _("Invoice"),
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"width": 150,
		},
		{"fieldname": "order_type", "label": _("Order Type"), "fieldtype": "Data", "width": 110},
		{
			"fieldname": "till",
			"label": _("Cashier Device"),
			"fieldtype": "Link",
			"options": "POS Profile",
			"width": 120,
		},
		{"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 130},
		{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 170},
		{"fieldname": "qty", "label": _("Qty"), "fieldtype": "Float", "width": 70},
		{"fieldname": "rate", "label": _("Rate"), "fieldtype": "Currency", "width": 100},
		{"fieldname": "sales", "label": _("Sales before VAT"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "amount", "label": _("Amount"), "fieldtype": "Currency", "width": 110},
	]

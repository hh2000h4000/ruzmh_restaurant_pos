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
from frappe.utils import flt, now_datetime

from restaurant_pos.utils.audit import log_audit
from restaurant_pos.utils.payment import is_credit_method
from restaurant_pos.utils.permissions import consume_override_token
from restaurant_pos.utils.shift import assert_may_sell, selling_till


def assert_returnable(order) -> str:
	"""BR-050 — there is nothing to return until there is an invoice."""
	if order.status != "closed" or not order.sales_invoice:
		frappe.throw(_("Order {0} has not been paid, so there is nothing to return.").format(order.name))

	if frappe.db.get_value("Sales Invoice", order.sales_invoice, "docstatus") != 1:
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
		"Sales Invoice Item",
		filters={"parent": invoice, "parenttype": "Sales Invoice"},
		fields=["name", "idx", "item_code", "item_name", "qty", "rate", "amount"],
		order_by="idx",
	)

	taken = _returned_quantities([row.name for row in rows])

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
			}
		)

	return {
		"order_name": order.name,
		"sales_invoice": invoice,
		"items": items,
		# BR-054 — the refund goes back the way the money came in, so the screen
		# needs to know what that was.
		"paid_with": _paid_with(invoice),
		"returns": _existing_returns(invoice),
		"fully_returned": all(row["returnable"] <= 0 for row in items),
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
		"Sales Invoice Item",
		filters={"sales_invoice_item": ("in", rows), "docstatus": 1},
		fields=["sales_invoice_item", "qty"],
	):
		taken[row.sales_invoice_item] = taken.get(row.sales_invoice_item, 0.0) + abs(flt(row.qty))

	return taken


def _paid_with(invoice: str) -> list[dict]:
	return [
		{"method": row.mode_of_payment, "amount": flt(row.amount)}
		for row in frappe.get_all(
			"Sales Invoice Payment",
			filters={"parent": invoice, "parenttype": "Sales Invoice"},
			fields=["mode_of_payment", "amount"],
			order_by="idx",
		)
	]


def _existing_returns(invoice: str) -> list[dict]:
	return frappe.get_all(
		"Sales Invoice",
		filters={"return_against": invoice, "docstatus": 1},
		fields=["name", "posting_date", "grand_total", "remarks"],
		order_by="creation",
	)


def create_return(
	order,
	*,
	items: list,
	reason: str,
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

	if not (reason or "").strip():
		frappe.throw(_("A reason is required for a return."))

	approved_by = _authorise_return(order, override_token)
	wanted = _validate_quantities(order, items)

	credit = _build_credit_note(invoice, wanted, reason, refund_method)

	log_audit(
		"return_created",
		branch=order.branch,
		pos_profile=order.pos_profile,
		restaurant_order=order.name,
		approved_by=approved_by,
		reason=reason.strip(),
		details={
			"sales_invoice": invoice,
			"credit_note": credit.name,
			"refund_amount": flt(credit.rounded_total or credit.grand_total),
			"items": [{"row": row, "qty": qty} for row, qty in wanted.items()],
		},
	)

	return {
		"order_name": order.name,
		"sales_invoice": invoice,
		"credit_note": credit.name,
		# Positive, because a cashier hands this much back. The document carries
		# it negative, which is the ledger's business and not the screen's.
		"refund_amount": abs(flt(credit.rounded_total or credit.grand_total)),
		"returnable": returnable(order),
	}


def _authorise_return(order, override_token: str | None) -> str | None:
	"""BR-055 — an older shift's sale is a manager's decision.

	The permission alone covers a refund the cashier is making against their own
	open shift, where they can still see the customer. Anything from a shift that
	has been counted and handed over is somebody else's drawer, so it takes a
	manager's PIN even from a cashier who holds `can_create_return`.
	"""
	from restaurant_pos.utils.order import authorise

	approved_by = authorise("can_create_return", override_token)

	till = selling_till(order.pos_profile)
	current = frappe.db.get_value("POS Opening Entry", till.name, "rpos_restaurant_shift") if till else None

	if order.restaurant_shift and order.restaurant_shift != current and not approved_by:
		approved_by = consume_override_token(override_token, "can_create_return")

	return approved_by


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

	return wanted


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


def _compose(invoice: str, wanted: dict[str, float]):
	"""ERPNext builds it; we trim it to what is actually coming back.

	`make_return_doc` produces a full reversal of the invoice. Dropping the rows
	nobody asked for and reducing the rest is how a **partial** return is made
	without hand-building an accounting document (`10` critical note 9).

	Returns an unsaved document, so the same code answers both "what would this
	come to" and "do it" — one arithmetic, not two that can drift.
	"""
	from erpnext.controllers.sales_and_purchase_return import make_return_doc

	credit = make_return_doc("Sales Invoice", invoice)

	kept = []
	for row in credit.items:
		qty = wanted.get(row.sales_invoice_item)
		if not qty:
			continue

		# Negative, because a credit note takes goods back.
		row.qty = -abs(flt(qty))
		row.stock_qty = None
		kept.append(row)

	credit.set("items", kept)
	credit.set_missing_values()
	credit.calculate_taxes_and_totals()
	return credit


def _build_credit_note(invoice: str, wanted: dict[str, float], reason: str, refund_method: str | None):
	credit = _compose(invoice, wanted)

	_apply_refund(credit, refund_method)
	credit.remarks = _("Return of {0}: {1}").format(invoice, reason.strip())

	credit.flags.ignore_permissions = True
	credit.insert()
	credit.submit()
	return credit


def _apply_refund(credit, refund_method: str | None) -> None:
	"""BR-054 — the money goes back the way it came, unless told otherwise.

	**One method, or say which.** A bill split across two methods has no obvious
	right answer for a partial refund, and splitting it by ratio would hand a
	customer two amounts for one returned dish. The cashier names the method
	instead; the screen offers the original ones first.
	"""
	due = flt(credit.rounded_total or credit.grand_total)

	original = _paid_with(credit.return_against)
	method = refund_method or (original[0]["method"] if len(original) == 1 else None)

	if not method:
		frappe.throw(_("This bill was paid more than one way. Choose how to refund it."))

	# D-029 — money that never entered a drawer does not come out of one. A
	# platform's order is settled on a statement, and so is its reversal.
	credit.is_pos = 0 if is_credit_method(method) else 1
	credit.set("payments", [])

	if credit.is_pos:
		credit.append("payments", {"mode_of_payment": method, "amount": -abs(due)})

	credit.set_posting_time = 1
	credit.posting_date = now_datetime().date()
	credit.posting_time = now_datetime().time()

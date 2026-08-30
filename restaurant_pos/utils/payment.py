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
from frappe.utils import flt, now_datetime

from restaurant_pos.utils import kitchen, totals
from restaurant_pos.utils.audit import log_audit
from restaurant_pos.utils.order import (
	assert_mutable,
	assert_transition,
	set_table_status,
)
from restaurant_pos.utils.permissions import (
	assert_within_discount_limit,
	consume_override_token,
	discount_override_action,
	get_pos_permission_set,
)

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
	promotion_applied: str | None = None,
	override_token: str | None = None,
) -> dict:
	"""Settle an order and submit its Sales Invoice (FR-2.7)."""
	# BR-044 is in here too (D-058): taking money is the sale, not a step after
	# it, and a draft held over from an earlier shift must not be settled into a
	# drawer that has already been counted and handed over.
	assert_mutable(order)

	if not order.items or all(row.status == "void" for row in order.items):
		frappe.throw(_("An empty order cannot be paid."))

	payments = _normalise(payments)
	_apply_discount(order, discount_type, discount_value, override_token)

	totals.calculate(order)
	order.save(ignore_permissions=True)

	_validate_methods(order, payments)
	settlement = _settlement_of(payments)
	change = _validate_amounts(order, payments) if settlement == "till" else 0.0

	invoice = _create_sales_invoice(order, payments, promotion_applied, settlement)

	# BR-016 — closed only once the invoice is submitted.
	assert_transition(order, "closed")
	order.sales_invoice = invoice.name
	order.status = "closed"
	order.closed_at = now_datetime()
	order.save(ignore_permissions=True)

	if order.table:
		# BR-061 / FR-2.7g — the table is not free until it has been cleaned.
		set_table_status(order.table, "cleaning", None)

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
	}


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def _normalise(payments) -> list[dict]:
	if isinstance(payments, str):
		payments = frappe.parse_json(payments)

	if not payments:
		frappe.throw(_("Select at least one payment method."))

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
			}
		)

	return rows


def is_credit_method(method: str) -> bool:
	"""Whether this method leaves the money owed rather than collected.

	A delivery platform has already taken the customer's money; a corporate
	account will pay on a statement. Either way nothing enters the till
	(``DECISIONS.md`` D-029).
	"""
	return bool(frappe.db.get_value("Mode of Payment", method, "rpos_is_credit"))


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

	return kinds.pop()


def _validate_methods(order, payments) -> None:
	"""BR-023 / BR-002 — the order type decides what may be used."""
	allowed = frappe.get_all(
		"OT Payment Method",
		filters={"parent": order.order_type, "parenttype": "Restaurant Order Type"},
		fields=["payment_method", "is_forced"],
	)

	forced = [row.payment_method for row in allowed if row.is_forced]
	permitted = {row.payment_method for row in allowed}

	for row in payments:
		if not frappe.db.exists("Mode of Payment", row["method"]):
			frappe.throw(_("Unknown payment method: {0}").format(row["method"]))

		if permitted and row["method"] not in permitted:
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


def _create_sales_invoice(order, payments, promotion_applied, settlement: str = "till"):
	"""Build and submit the invoice through ERPNext's own controller.

	Never bypassed (`10` critical note 9): the controller is what computes tax,
	posts the ledger, moves stock and gives ZATCA integrations something to sign.
	"""
	profile = frappe.get_cached_doc("POS Profile", order.pos_profile)
	customer = order.customer or profile.customer
	if not customer:
		frappe.throw(_("Set a default customer on POS Profile {0}.").format(order.pos_profile))

	invoice = frappe.new_doc("Sales Invoice")
	invoice.update(
		{
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
			# 04 §6 — stock leaves through the Sales Invoice. ERPNext skips
			# non-stock items, so a menu of prepared dishes is unaffected.
			"update_stock": 1,
			"set_warehouse": profile.warehouse,
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
				fields=["charge_type", "account_head", "description", "rate", "cost_center"],
				order_by="idx",
			),
		)

	for row in order.items:
		if row.status == "void":
			continue

		invoice.append(
			"items",
			{
				"item_code": row.item,
				"qty": flt(row.qty),
				"rate": flt(row.amount) / flt(row.qty) if flt(row.qty) else flt(row.rate),
				"warehouse": profile.warehouse,
				"cost_center": profile.get("cost_center"),
			},
		)

	if flt(order.discount_amount):
		# FR-10.4 — the discount reduces the net, and ERPNext then recomputes VAT.
		invoice.apply_discount_on = "Net Total"
		invoice.discount_amount = flt(order.discount_amount)

	for row in payments:
		invoice.append("payments", {"mode_of_payment": row["method"], "amount": row["amount"]})

	if promotion_applied:
		invoice.remarks = f"{invoice.remarks} | {_('Promotion')}: {promotion_applied}"

	invoice.flags.ignore_permissions = True
	invoice.insert()
	invoice.submit()
	return invoice


def _send_kitchen_if_due(order) -> list:
	"""FR-2.7e — order types configured to hold the ticket until payment."""
	when = frappe.db.get_value("Restaurant Order Type", order.order_type, "send_to_kitchen_on")
	if when != "payment":
		return []

	if not any(row.status == "pending" for row in order.items):
		return []

	return kitchen.send_to_kitchen(order)["kots_created"]

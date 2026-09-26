# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Whitelisted payment endpoints.

Replay protection matters more here than anywhere else: a retried payment is a
duplicate invoice, duplicate revenue and a duplicate ZATCA submission.

Refs: 07_API_Design.md §3, FR-2.7, 09 §8
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from restaurant_pos.utils import coupons, idempotency, loyalty, promotions, totals
from restaurant_pos.utils import order as orders
from restaurant_pos.utils import payment as service
from restaurant_pos.utils.gift_card import is_gift_card_method
from restaurant_pos.utils.permissions import get_pos_permission_set, validate_branch_access


@frappe.whitelist()
def process_payment(
	order_name: str,
	payments: list | str,
	discount_type: str | None = None,
	discount_value: float = 0,
	promotion: str | None = None,
	loyalty_points_redeemed: float = 0,
	manager_override_token: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Settle an order and submit its Sales Invoice (FR-2.7)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = frappe.get_doc("Restaurant Order", order_name)
	validate_branch_access(order.branch)

	# A second belt against a duplicate invoice: even without a queue_id, an
	# order that is already closed must not be paid again (BR-016).
	if order.sales_invoice:
		frappe.throw(_("Order {0} was already paid — invoice {1}.").format(order.name, order.sales_invoice))

	result = service.process_payment(
		order,
		payments=payments,
		discount_type=discount_type,
		discount_value=discount_value,
		promotion=promotion,
		override_token=manager_override_token,
		# FR-10.5, D-189 — spent as a discount and checked against the balance
		# under a lock, inside the same transaction as the invoice.
		loyalty_points=cint(loyalty_points_redeemed),
	)

	idempotency.remember(
		queue_id,
		"process_payment",
		result,
		reference_doctype="Restaurant Order",
		reference_name=order.name,
	)
	return result


@frappe.whitelist()
def promotion_offers(order_name: str) -> dict:
	"""What this bill qualifies for, and whether this cashier may choose (`D-165`).

	Read-only: being shown what is on offer is not applying it, so it takes no
	``queue_id`` and asks for no permission. The **right to choose** is reported
	beside the list, so the screen can grey the choice rather than let a cashier
	pick one and be refused after telling the customer a price (`D-125`).
	"""
	order = frappe.get_doc("Restaurant Order", order_name)
	validate_branch_access(order.branch)

	return {
		"offers": promotions.offers_for(order),
		"may_choose": bool(get_pos_permission_set().get("can_manual_promotion")),
	}


@frappe.whitelist()
def preview_totals(
	order_name: str,
	discount_type: str | None = None,
	discount_value: float = 0,
	promotion: str | None = None,
	loyalty_points: int = 0,
) -> dict:
	"""What the order would come to with this discount and promotion, unapplied.

	The payment screen has to show the customer a figure before charging, and
	the frontend never computes money (`CLAUDE.md` §5.1). Nothing is saved: the
	document is loaded, the totals recalculated in memory, and discarded.

	Also reports whether the cashier may apply it, so the UI can ask for a
	manager before the customer is told a price nobody can honour.
	"""
	order = frappe.get_doc("Restaurant Order", order_name)
	validate_branch_access(order.branch)

	order.discount_type = discount_type
	order.discount_value = flt(discount_value)
	# The promotion travels the same road as the discount, because it is the same
	# question — *reduce this bill* — and a second mechanism for it is how the
	# two come to disagree (`D-165`, §5.5). Set in memory and discarded, like the
	# discount beside it: nothing here is saved.
	order.chosen_promotion = promotion or None
	# And the points, for the same reason (`D-189`): a third way to reduce the
	# bill, previewed on the one road, never a second mechanism beside it.
	order.loyalty_points = max(0, cint(loyalty_points))
	totals.calculate(order)

	percentage = service.discount_percentage(order, discount_type, discount_value)
	ceiling = flt(get_pos_permission_set().get(service.CEILING))

	return {
		# **Said before the cashier types, not after they are refused** (`D-125`,
		# `D-169`). An offer marked "does not combine with a manual discount"
		# refuses the discount at Confirm; the screen has to be able to grey the
		# controls and name the offer, or the rule is a wall with no sign on it.
		"discount_blocked_by": promotions.blocks_a_discount(order),
		"subtotal": order.subtotal,
		"discount_amount": order.discount_amount,
		**promotions.on_the_bill(order),
		**loyalty.on_the_bill(order),
		"tax_amount": order.tax_amount,
		"total_amount": order.total_amount,
		"discount_percentage": flt(percentage, 2),
		"max_discount_percentage": ceiling,
		"requires_override": percentage > ceiling,
	}


@frappe.whitelist()
def split_evenly(order_name: str, ways: int) -> dict:
	"""What each person owes when a table pays "قسّمها علينا" (FR-10.1).

	**This makes no second bill.** Guests asking to split are asking to hand
	over money separately, not to be invoiced separately — so the order stays
	one order, the payment takes several rows, and the sale keeps one Sales
	Invoice, one ZATCA QR and one line in the day's takings. Every serious POS
	treats an even split this way; a split that manufactured four invoices for
	one table would be four documents to reconcile and four to report.

	Splitting the bill *by item* is a different feature and does need a second
	document, because the items themselves move.

	The shares are computed here rather than on the till because they are money
	(`CLAUDE.md` §5.1), and because getting the last five halalas right is the
	entire difficulty — see :func:`totals.split_evenly`.
	"""
	order = frappe.get_doc("Restaurant Order", order_name)
	validate_branch_access(order.branch)

	currency = frappe.db.get_value("POS Profile", order.pos_profile, "currency") or totals.DEFAULT_CURRENCY
	shares = totals.split_evenly(order.total_amount, ways, currency=currency)

	return {
		"order_name": order.name,
		"total_amount": order.total_amount,
		"ways": len(shares),
		"shares": shares,
	}


@frappe.whitelist()
def get_payment_summary(order_name: str) -> dict:
	"""What the payment screen needs: totals and the permitted methods (FR-10.1)."""
	order = frappe.get_doc("Restaurant Order", order_name)
	validate_branch_access(order.branch)

	allowed = service.allowed_methods(order)

	# Only a method that takes notes can be handed more than the bill and give
	# change back, so only those are offered round denominations to tap
	# (`D-124`). Read from ERPNext's own `Mode of Payment.type`, the same source
	# the drawer opens on (`D-093`) — a restaurant may call cash anything.
	for row in allowed:
		row["is_cash"] = 1 if service.is_cash(row["payment_method"]) else 0
		# And which ones leave the money owed instead of collected. A bill is
		# settled at the till **or** billed to an account, never both (`D-029`),
		# and the screen has to stop the mix at the tap rather than let the
		# server refuse it after the cashier has taken two tenders (`D-125`).
		row["is_credit"] = 1 if service.is_credit_method(row["payment_method"]) else 0
		# `D-256` — and which one spends a gift card, so the screen knows to ask
		# *which* card before taking anything. Marked by the server rather than
		# matched by name on the device: a manager may rename the method, and a
		# till comparing strings would quietly stop asking.
		row["is_gift_card"] = 1 if is_gift_card_method(row["payment_method"]) else 0

	return {
		"order_name": order.name,
		"subtotal": order.subtotal,
		"discount_amount": order.discount_amount,
		**promotions.on_the_bill(order),
		**loyalty.on_the_bill(order),
		"tax_amount": order.tax_amount,
		"total_amount": order.total_amount,
		"payment_methods": allowed,
		"already_paid": bool(order.sales_invoice),
		"sales_invoice": order.sales_invoice,
		# A setup fault that no tender can get past, said while the queue can
		# still be told rather than thrown from the invoice after the money has
		# been handed over (`D-125`).
		"blocker": service.invoice_blocker(order),
	}


@frappe.whitelist(methods=["POST"])
def apply_coupon(order_name: str, code: str) -> dict:
	"""Put a guest's coupon on the bill, or say plainly why it will not go on (`D-248`).

	**POST, because it writes.** The code lands on the order, which is what the
	totals then read — the promotion behind it is priced by the same engine as
	every other offer, so the screen and the invoice cannot disagree.
	"""
	order = frappe.get_doc("Restaurant Order", order_name)
	validate_branch_access(order.branch)
	orders.assert_mutable(order)

	accepted = coupons.attach(order, code)
	totals.calculate(order)

	return {"coupon": accepted, **promotions.on_the_bill(order), "total_amount": order.total_amount}


@frappe.whitelist(methods=["POST"])
def remove_coupon(order_name: str) -> dict:
	"""Take it back off — a guest who produced the wrong code, or changed their mind."""
	order = frappe.get_doc("Restaurant Order", order_name)
	validate_branch_access(order.branch)
	orders.assert_mutable(order)

	coupons.detach(order)
	totals.calculate(order)

	return {"coupon": None, **promotions.on_the_bill(order), "total_amount": order.total_amount}

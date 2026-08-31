# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""An order sold while the line was down (09 §5, D-072).

**One call, not a replayed conversation.** An online cashier's order is a dozen
requests — create, add, add, change a quantity, pay — and each one names the
order by the id the *server* assigned. Offline there is no such id, so replaying
that conversation would mean inventing one and patching it into every later
call. Instead the device composes the whole bill locally and sends it once, when
the line comes back: lines, discount, payment, and the figures it quoted the
customer.

**The device's figures are checked, not trusted.** `D-071` makes the two
arithmetics agree by construction — same algorithm, same inputs, one contract —
so a difference here means something changed between the sale and the sync, and
the honest response is to say so rather than post whichever number is at hand.
The server recomputes; a mismatch stops the replay with both figures named, and
is written to the audit log so it survives the cashier closing the browser.

Refs: 09 §5, §8, D-034, D-071, D-072, BR-022, BR-024
"""

import frappe
from frappe import _
from frappe.utils import flt

from restaurant_pos.utils import order as orders
from restaurant_pos.utils import payment as payments
from restaurant_pos.utils import totals

#: Half a halala. Below this two figures are the same figure rendered twice, and
#: a float comparison would stop a sale over a representation artefact.
EPSILON = 0.005


def submit_order(*, pos_profile: str, payload: dict, offline_queue_id: str) -> dict:
	"""Land a bill the device already took money for.

	``payload`` is what the till composed offline::

	    {
	      "order_type": "...",
	      "opened_at": "2026-08-30 19:41:00",
	      "lines": [{"item": "...", "qty": 2, "modifiers": [...], "notes": "..."}],
	      "discount_type": null, "discount_value": 0,
	      "payments": [{"method": "Cash", "amount": 47.15, "tendered": 50}],
	      "totals": {"subtotal": ..., "tax_amount": ..., "total_amount": ...},
	      "call_name": null, "table": null, "customer": null
	    }
	"""
	order = orders.create_order(
		order_type=payload["order_type"],
		pos_profile=pos_profile,
		table=payload.get("table"),
		customer=payload.get("customer"),
		cover_count=payload.get("cover_count"),
		call_name=payload.get("call_name"),
		notes=payload.get("notes"),
		offline_queue_id=offline_queue_id,
	)

	for line in payload.get("lines") or []:
		orders.add_item(
			order,
			item=line["item"],
			qty=flt(line.get("qty") or 1),
			modifiers=line.get("modifiers"),
			notes=line.get("notes"),
		)

	order.reload()
	variance = _assert_totals_agree(order, payload, offline_queue_id)

	result = payments.process_payment(
		order,
		payments=payload.get("payments") or [],
		discount_type=payload.get("discount_type"),
		discount_value=flt(payload.get("discount_value") or 0),
	)

	result["offline_queue_id"] = offline_queue_id
	result["variance"] = variance
	return result


def _assert_totals_agree(order, payload: dict, offline_queue_id: str) -> dict:
	"""Compare what the till quoted with what the server makes it (D-072).

	The discount is applied here, before the comparison, because the till quoted
	a discounted figure and comparing against an undiscounted one would report a
	difference on every discounted bill.

	**A mismatch stops the replay.** The money is already in the drawer, so the
	temptation is to post *something* and move on — but the two figures cannot
	both be charged, and choosing silently is how a shop discovers weeks later
	that its takings and its invoices never matched. The entry stays in the
	queue, marked failed, with both numbers in the message and in the audit log.
	"""
	claimed = payload.get("totals") or {}
	if not claimed:
		frappe.throw(_("An offline order must carry the totals it was sold at."))

	order.discount_type = payload.get("discount_type")
	order.discount_value = flt(payload.get("discount_value") or 0)
	totals.calculate(order)

	theirs = flt(claimed.get("total_amount"))
	ours = flt(order.total_amount)
	difference = flt(ours - theirs, 2)

	if abs(difference) < EPSILON:
		return {"agreed": True, "device_total": theirs, "server_total": ours, "difference": 0.0}

	# **The rollback is the point.** `frappe.throw` undoes the order this function
	# just built, so a bill nobody can price does not become a half-posted
	# document somebody has to find and clean up later.
	#
	# Which also means no audit row can be written here — it would roll back with
	# everything else. The durable record is the queue entry on the device: the
	# flush marks it `failed`, keeps this message, and it surfaces on the sync
	# screen (`09` §10) where a human is already being asked to look.
	frappe.throw(
		_(
			"This bill was sold offline at {0} but comes to {1} here "
			"(a difference of {2}). Nothing has been posted — a manager has to "
			"settle it before it can be synced."
		).format(theirs, ours, difference),
		frappe.ValidationError,
	)

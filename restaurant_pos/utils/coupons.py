# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Presenting a coupon, and spending it (`D-248`).

**A key, not a second discount engine.** The code names a promotion and the
promotion does the arithmetic — priority, item scope, the per-line claim, the
mark on the bill. Anything else would be a second set of rules to keep in step
with the first (`CLAUDE.md` §5.5).

**Checked when it is typed, counted when the bill is paid.** The two are apart on
purpose: the cashier has to know at once whether the code is good, and the use is
only real once money changed hands — a code typed onto a bill that was then
cancelled was never spent.

**And the count never refuses a payment.** A code that runs out between being
typed and being paid is a race worth one extra use; refusing the customer
standing at the counter, over a figure the screen already quoted them, is not.

Refs: FR-11.1, D-163, D-248
"""

import frappe
from frappe import _
from frappe.utils import getdate, today

#: What the till needs to know about a code it just accepted.
SUMMARY = ("name", "coupon_code", "promotion", "campaign", "max_uses", "used")


def attach(order, code: str) -> dict:
	"""Put a coupon on this bill, or say why it cannot go on.

	The refusals are deliberately specific — an expired code and a used-up code
	are different problems and the cashier can do something about each.
	"""
	coupon = find(code)
	if not coupon:
		frappe.throw(_("No coupon with that code."))

	_assert_usable(coupon)

	if not frappe.db.get_value("Restaurant Promotion", coupon.promotion, "is_active"):
		frappe.throw(_("The offer behind this coupon is not running."))

	_set(order, coupon.name)
	return {field: coupon.get(field) for field in SUMMARY}


def detach(order) -> None:
	_set(order, None)


def _set(order, coupon: str | None) -> None:
	"""Put the code on the bill and price it again.

	**Recalculated and saved, not written with `db_set`.** A coupon changes what
	is owed, and the stored total is what the kitchen screen, the payment screen
	and the invoice all read — leaving it at the figure from before the code was
	presented would quote the guest one number and charge another (§5.1).
	"""
	from restaurant_pos.utils import totals

	order.coupon = coupon
	totals.calculate(order)
	order.save(ignore_permissions=True)


def find(code: str) -> frappe._dict | None:
	wanted = (code or "").strip().upper()
	if not wanted:
		return None

	return frappe.db.get_value(
		"POS Coupon",
		{"coupon_code": wanted},
		[*SUMMARY, "is_active", "valid_from", "valid_to"],
		as_dict=True,
	)


def unlocks(order, promotion: str) -> bool:
	"""Whether this bill carries a coupon for that promotion.

	Read by the engine on every candidate, so it asks the database once per bill
	rather than once per promotion.
	"""
	held = order.get("coupon")
	if not held:
		return False

	return frappe.get_cached_value("POS Coupon", held, "promotion") == promotion


def consume(order) -> None:
	"""Count one use, when the bill is settled.

	Idempotent by the order: a bill counts its coupon once however many times the
	settlement is replayed, which the offline queue does by design (`09` §8).
	"""
	coupon = order.get("coupon")
	if not coupon or order.get("coupon_spent"):
		return

	frappe.db.set_value("POS Coupon", coupon, "used", _used(coupon) + 1, update_modified=False)
	order.db_set("coupon_spent", 1, update_modified=False)


def _used(coupon: str) -> int:
	return int(frappe.db.get_value("POS Coupon", coupon, "used") or 0)


def _assert_usable(coupon) -> None:
	if not coupon.is_active:
		frappe.throw(_("This coupon is switched off."))

	day = getdate(today())
	if coupon.valid_from and day < getdate(coupon.valid_from):
		frappe.throw(_("This coupon does not start until {0}.").format(coupon.valid_from))

	if coupon.valid_to and day > getdate(coupon.valid_to):
		frappe.throw(_("This coupon expired on {0}.").format(coupon.valid_to))

	if coupon.max_uses and int(coupon.used or 0) >= int(coupon.max_uses):
		frappe.throw(_("This coupon has been used already."))

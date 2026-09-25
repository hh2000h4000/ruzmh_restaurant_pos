# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

from datetime import timedelta

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_datetime


def _title_of(promotion: str | None) -> str:
	"""What to call a promotion on the story — its Arabic name, or its id."""
	if not promotion:
		return ""

	titles = frappe.get_cached_value("Restaurant Promotion", promotion, ["title_ar", "title"])
	return (titles[0] or titles[1] or promotion) if titles else promotion


#: How far the clock may step backwards between opening a bill and settling it
#: before that is a fact rather than a fault (`D-261`).
#:
#: **This rule is here to catch nonsense** — a bill closed yesterday and opened
#: today — and it was written as a strict comparison, which also catches a clock
#: correction landing between two `now_datetime()` calls. Measured, not guessed:
#: sampling the dev machine's clock for twenty seconds caught it stepping
#: **back 1.218 seconds** once, and that is exactly how a payment came to be
#: refused with "Closed At cannot be earlier than Opened At" on a bill opened and
#: settled in the same second.
#:
#: A restaurant server whose time is corrected by NTP can do the same thing, and
#: the cost there is a cashier who cannot take money while a queue waits. Five
#: seconds is far more than any correction of that kind and far less than any
#: mistake worth refusing a sale over.
CLOCK_SLACK = timedelta(seconds=5)


class RestaurantOrder(Document):
	def validate(self):
		self.validate_order_type_change()
		self.validate_cover_count()
		self.validate_discount()
		self.validate_items()
		self.validate_lifecycle()

	def on_update(self):
		self.record_the_promotion()

	def record_the_promotion(self):
		"""Put the offer on the bill's story (`FR-12.7`, `D-172`).

		**Money came off and the story said nothing.** A bill of 82.00 settled at
		46.00 because an offer took 36.00, and its timeline read: opened, three
		items added. Anything that happens to a bill is supposed to be written
		down, and this was the one movement that changed the total without a
		person doing it — so the only record of it was the total itself.

		**On change, not on every recalculation.** `totals.calculate` runs on
		every tap: adding a dish, changing a quantity, opening the payment
		screen. Logging there would write a line per keystroke and bury the story
		it was meant to tell. What is worth recording is the offer *changing* —
		arriving, being swapped for a better one, or falling away when the bill
		drops back under a minimum — which happens once or twice on a real bill.

		**And on save, so a preview leaves no trace.** `preview_totals`
		recalculates in memory and never saves (`FR-11.2`); a cashier reading
		what a discount would come to has not applied anything, and a story that
		said otherwise would be worse than none.
		"""
		before = self._doc_before_save.promotion if self._doc_before_save else None
		if before == self.promotion:
			return

		from restaurant_pos.utils import activity

		if not self.promotion:
			activity.log(self, "promotion_removed", subject=_title_of(before))
			return

		activity.log(
			self,
			"promotion_applied",
			subject=f"{_title_of(self.promotion)} · {flt(self.promotion_amount):.2f}",
			details={
				"promotion": self.promotion,
				"amount": flt(self.promotion_amount),
				# Whether anybody chose it, or the engine did. A manual offer is
				# somebody spending the shop's money and is audited as well
				# (`D-165`); an automatic one is the shop's own rule firing, and
				# this line is the whole record of it.
				"chosen_by_hand": bool(self.chosen_promotion),
				"replaced": before,
			},
		)

	def validate_order_type_change(self):
		"""The type may change, but only through the one path that handles it.

		``order_type`` used to be ``set_only_once``, which stopped a cashier
		turning a takeaway into a dine-in — something a restaurant does all day
		(D-038). The guard moves here rather than disappearing: the type decides
		the price list, the kitchen routing and the payment methods, so a stray
		``db.set_value`` elsewhere would leave an order priced from a list it no
		longer sells from. ``utils/order.change_order_type`` sets the flag after
		it has re-priced and re-routed.
		"""
		if self.is_new() or self.flags.rpos_order_type_change:
			return

		if self.has_value_changed("order_type"):
			frappe.throw(
				_("An order's type is changed through the order screen, not by editing it."),
				frappe.ValidationError,
			)

	def validate_cover_count(self):
		if cint(self.cover_count) < 0:
			frappe.throw(_("Cover Count cannot be negative."))

	def validate_discount(self):
		if not self.discount_type:
			self.discount_value = 0
			return

		if flt(self.discount_value) < 0:
			frappe.throw(_("Discount Value cannot be negative."))

		if self.discount_type == "percentage" and flt(self.discount_value) > 100:
			frappe.throw(_("A percentage discount cannot exceed 100."))

	def validate_items(self):
		for row in self.items or []:
			if flt(row.qty) <= 0:
				frappe.throw(_("Row #{0}: Qty must be greater than zero.").format(row.idx))

			if flt(row.rate) < 0:
				frappe.throw(_("Row #{0}: Rate cannot be negative.").format(row.idx))

			if cint(row.course) < 0:
				frappe.throw(_("Row #{0}: Course cannot be negative.").format(row.idx))

			if row.status == "void" and not (row.void_reason or "").strip():
				frappe.throw(_("Row #{0}: Void Reason is required for a voided item.").format(row.idx))

	def validate_lifecycle(self):
		if self.status == "cancelled" and not (self.cancel_reason or "").strip():
			frappe.throw(_("Cancel Reason is required when an order is cancelled."))

		if (
			self.closed_at
			and self.opened_at
			and get_datetime(self.opened_at) - get_datetime(self.closed_at) > CLOCK_SLACK
		):
			frappe.throw(_("Closed At cannot be earlier than Opened At."))

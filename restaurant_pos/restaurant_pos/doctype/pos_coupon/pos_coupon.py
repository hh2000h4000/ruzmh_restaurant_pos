# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""A code that unlocks an offer — the influencer's coupon (`D-248`).

**The coupon carries no discount of its own.** It names a `Restaurant Promotion`
and the promotion does what promotions already do: the priority, the item scope,
the per-line claim, the mark on the bill and the row in the order's log. A code
with its own percentage would have been a second discount engine beside the one
we have, disagreeing with it eventually (`CLAUDE.md` §5.5).

**Both shapes the user asked for come out of one field.** `max_uses = 0` is the
shared code an influencer reads out to everybody; `max_uses = 1` on a generated
batch gives every guest a code only they can spend.

Refs: FR-11.1, D-163, D-248
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class POSCoupon(Document):
	def before_validate(self):
		# Matched in upper case, so it is stored that way: a guest reading a code
		# down the phone does not say which letters were capitals.
		self.coupon_code = (self.coupon_code or "").strip().upper()

	def validate(self):
		if not self.coupon_code:
			frappe.throw(_("A coupon needs a code."))

		if self.max_uses and self.max_uses < 0:
			frappe.throw(_("Maximum Uses cannot be negative."))

		if self.valid_from and self.valid_to and getdate(self.valid_from) > getdate(self.valid_to):
			frappe.throw(_("Valid To cannot be earlier than Valid From."))

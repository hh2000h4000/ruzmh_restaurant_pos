# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""A card carrying money the restaurant already took (`D-256`).

**Not a discount.** A coupon says *take something off*; a gift card says *this
guest has already paid*. The bill's full price is charged, the VAT is charged on
all of it, and the card settles the total like cash does.

Refs: FR-11.5, D-256
"""

import frappe
from frappe import _
from frappe.model.document import Document


class POSGiftCard(Document):
	def before_validate(self):
		# Read off a plastic card and typed by a cashier: the case is not part
		# of the number, the same rule `POS Coupon` follows.
		self.card_number = (self.card_number or "").strip().upper()

	def validate(self):
		if self.balance and self.balance < 0:
			frappe.throw(_("A gift card cannot hold less than nothing."))

	def on_trash(self):
		"""**A card is never deleted.** It is money the restaurant owes.

		Deleting one erases a liability from the books while the guest still
		holds the plastic, and the entries that explain the balance would be
		orphaned. A card taken out of use is switched off, which leaves the
		balance and its history where an accountant can still find them.
		"""
		frappe.throw(_("A gift card cannot be deleted. Switch it off instead."))

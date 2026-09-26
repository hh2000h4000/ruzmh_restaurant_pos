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

		self.mirror_the_ledger()

	def mirror_the_ledger(self) -> None:
		"""**The balance is a copy of the entries, so make it one** (`D-260`).

		It is read-only on the form, which stops a manager editing it and stops
		nothing else: a card *created* in the desk carries whatever was typed, and
		the entries behind it are empty. The form then says 200 while the till
		says the card holds nothing — two screens disagreeing about money, which
		is the worst shape a defect can take. The user found it by asking how a
		company would order cards.

		Forced rather than refused, because there is a legitimate way to put a
		balance on a card and it is not this one: `utils/gift_card.issue`, which
		writes the entry and posts the liability. What is refused is a number with
		nothing behind it.
		"""
		from restaurant_pos.utils.gift_card import balance_of

		self.balance = balance_of(self.card_number) if not self.is_new() else 0.0

	def on_trash(self):
		"""**A card the books know is never deleted.** It is money the restaurant owes.

		Deleting one erases a liability from the books while the guest still
		holds the plastic, and the entries that explain the balance would be
		orphaned. A card taken out of use is switched off, and one issued by
		mistake is cancelled (`utils/gift_card.void`), which reverses its entry
		and keeps its history where an accountant can still find it.

		**A record the books never saw is only a record** (`D-267`): no journal
		entry and no invoice on any of its rows — a card typed into the desk
		before that was closed off, or one issued while the method had no
		account. The user asked why those could not go; they can, with their rows.
		"""
		posted = frappe.get_all(
			"POS Gift Card Entry",
			filters={"gift_card": self.name},
			or_filters={"journal_entry": ("is", "set"), "sales_invoice": ("is", "set")},
			limit=1,
		)
		if posted:
			frappe.throw(
				_("A gift card the books know cannot be deleted. Cancel its issue, or switch it off.")
			)

		frappe.flags.rpos_deleting_gift_card = self.name
		try:
			for entry in frappe.get_all(
				"POS Gift Card Entry", filters={"gift_card": self.name}, pluck="name"
			):
				frappe.delete_doc("POS Gift Card Entry", entry, ignore_permissions=True)
		finally:
			frappe.flags.rpos_deleting_gift_card = None

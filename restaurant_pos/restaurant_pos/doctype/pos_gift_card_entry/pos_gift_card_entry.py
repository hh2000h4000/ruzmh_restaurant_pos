# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""One movement on one gift card (`D-256`).

**The entries are the record; the balance on the card is a convenience.** Every
figure an accountant is asked to trust — the liability outstanding, what a card
has left, what was spent on which bill — is a sum of these rows. The balance
field exists so a till need not add them up at the counter.

Refs: FR-11.5, D-256
"""

import frappe
from frappe import _
from frappe.model.document import Document


class POSGiftCardEntry(Document):
	def on_trash(self):
		"""Money the restaurant took or gave back leaves a row that stays.

		**Except with its card**, when that card never reached the books
		(`D-267`): `POSGiftCard.on_trash` has checked, and names the card here.
		"""
		if frappe.flags.rpos_deleting_gift_card == self.gift_card:
			return
		frappe.throw(_("A gift card entry cannot be deleted."))

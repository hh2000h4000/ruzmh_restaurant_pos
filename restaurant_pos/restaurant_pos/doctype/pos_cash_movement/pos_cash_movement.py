# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Money in or out of an open drawer, for something that is not a sale.

**Why this exists at all.** The cashier runs out of change, or sends somebody
for a bag of ice, and the notes leave the till. Nothing recorded it, so at
closing the drawer was short by exactly that amount and the count blamed the
person holding it. Every till on the market has this — classic registers print
it as PAID IN and PAID OUT — and ours did not (`D-245`).

**Written once and never edited.** Every field is read-only and the row is
created by `utils/cash_movement`, because a drawer's history is evidence: a
figure somebody can go back and adjust proves nothing about the notes that were
actually in the box.

Refs: FR-8.3, BR-041, D-245
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class POSCashMovement(Document):
	def validate(self):
		if flt(self.amount) <= 0:
			frappe.throw(_("A cash movement must be more than zero."))

		if self.direction not in ("in", "out"):
			frappe.throw(_("A cash movement is either in or out."))

		if not (self.reason or "").strip():
			frappe.throw(_("Say what the money was for."))

	def on_trash(self):
		"""The drawer's history is not editable, and deleting a row rewrites it."""
		frappe.throw(_("A cash movement cannot be deleted. It is the drawer's record."))

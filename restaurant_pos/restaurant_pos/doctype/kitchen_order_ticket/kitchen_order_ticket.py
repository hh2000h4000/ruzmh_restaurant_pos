# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class KitchenOrderTicket(Document):
	def validate(self):
		self.validate_items()

	def validate_items(self):
		if not self.items:
			frappe.throw(_("A Kitchen Order Ticket must contain at least one item."))

		for row in self.items:
			if flt(row.qty) <= 0:
				frappe.throw(_("Row #{0}: Qty must be greater than zero.").format(row.idx))

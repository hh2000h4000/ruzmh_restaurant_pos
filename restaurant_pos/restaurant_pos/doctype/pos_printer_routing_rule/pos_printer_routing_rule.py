# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class POSPrinterRoutingRule(Document):
	def validate(self):
		self.validate_target_specificity()
		self.validate_priority()

	def validate_target_specificity(self):
		if self.item and self.item_group:
			frappe.throw(_("Set either Item or Item Group on a routing rule, not both."))

	def validate_priority(self):
		if cint(self.priority) < 0:
			frappe.throw(_("Priority cannot be negative."))

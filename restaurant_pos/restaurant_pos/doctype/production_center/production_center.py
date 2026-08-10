# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ProductionCenter(Document):
	def validate(self):
		self.validate_output_target()
		self.validate_printers()
		# Kitchen tickets never carry prices (BR-075).
		self.show_prices_on_kot = 0

	def validate_output_target(self):
		if not self.printer and not self.has_kds:
			frappe.throw(_("A Production Center needs a Printer, a KDS, or both."))

	def validate_printers(self):
		if self.fallback_printer and self.fallback_printer == self.printer:
			frappe.throw(_("Fallback Printer must be different from the primary Printer."))

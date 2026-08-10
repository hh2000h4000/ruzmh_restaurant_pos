# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class RestaurantSection(Document):
	def validate(self):
		self.apply_section_type_defaults()

	def apply_section_type_defaults(self):
		"""`has_tables` follows the section type unless the user overrides it."""
		if self.section_type in ("counter", "takeaway", "delivery"):
			self.has_tables = 0
		elif self.is_new() and not self.has_tables:
			self.has_tables = 1

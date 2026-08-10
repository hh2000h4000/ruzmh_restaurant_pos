# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


class RestaurantTable(Document):
	def validate(self):
		self.validate_capacity()
		self.validate_geometry()

	def validate_capacity(self):
		if cint(self.capacity) < 0:
			frappe.throw(_("Capacity cannot be negative."))

	def validate_geometry(self):
		for fieldname in ("pos_x", "pos_y"):
			if flt(self.get(fieldname)) < 0:
				frappe.throw(_("{0} cannot be negative.").format(_(self.meta.get_label(fieldname))))

		for fieldname in ("width", "height"):
			if self.get(fieldname) is not None and flt(self.get(fieldname)) < 0:
				frappe.throw(_("{0} cannot be negative.").format(_(self.meta.get_label(fieldname))))

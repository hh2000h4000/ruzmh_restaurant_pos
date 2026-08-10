# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class RestaurantFloorPlan(Document):
	def validate(self):
		self.validate_canvas()

	def validate_canvas(self):
		for fieldname in ("canvas_width", "canvas_height"):
			if cint(self.get(fieldname)) <= 0:
				frappe.throw(_("{0} must be greater than zero.").format(_(self.meta.get_label(fieldname))))

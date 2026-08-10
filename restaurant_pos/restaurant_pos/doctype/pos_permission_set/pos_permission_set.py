# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class POSPermissionSet(Document):
	def validate(self):
		self.validate_discount_limits()

	def validate_discount_limits(self):
		for fieldname in ("max_item_discount_pct", "max_order_discount_pct"):
			value = flt(self.get(fieldname))
			if not 0 <= value <= 100:
				frappe.throw(_("{0} must be between 0 and 100.").format(_(self.meta.get_label(fieldname))))

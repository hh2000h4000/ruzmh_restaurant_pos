# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_datetime


class RestaurantOrder(Document):
	def validate(self):
		self.validate_cover_count()
		self.validate_discount()
		self.validate_items()
		self.validate_lifecycle()

	def validate_cover_count(self):
		if cint(self.cover_count) < 0:
			frappe.throw(_("Cover Count cannot be negative."))

	def validate_discount(self):
		if not self.discount_type:
			self.discount_value = 0
			return

		if flt(self.discount_value) < 0:
			frappe.throw(_("Discount Value cannot be negative."))

		if self.discount_type == "percentage" and flt(self.discount_value) > 100:
			frappe.throw(_("A percentage discount cannot exceed 100."))

	def validate_items(self):
		for row in self.items or []:
			if flt(row.qty) <= 0:
				frappe.throw(_("Row #{0}: Qty must be greater than zero.").format(row.idx))

			if flt(row.rate) < 0:
				frappe.throw(_("Row #{0}: Rate cannot be negative.").format(row.idx))

			if cint(row.course) < 0:
				frappe.throw(_("Row #{0}: Course cannot be negative.").format(row.idx))

			if row.status == "void" and not (row.void_reason or "").strip():
				frappe.throw(_("Row #{0}: Void Reason is required for a voided item.").format(row.idx))

	def validate_lifecycle(self):
		if self.status == "cancelled" and not (self.cancel_reason or "").strip():
			frappe.throw(_("Cancel Reason is required when an order is cancelled."))

		if self.closed_at and self.opened_at and get_datetime(self.closed_at) < get_datetime(self.opened_at):
			frappe.throw(_("Closed At cannot be earlier than Opened At."))

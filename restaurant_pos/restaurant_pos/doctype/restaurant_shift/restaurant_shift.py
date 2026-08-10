# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime


class RestaurantShift(Document):
	def validate(self):
		self.validate_closure()

	def validate_closure(self):
		if self.status == "closed":
			if not self.closed_by:
				self.closed_by = frappe.session.user
			if not self.closed_at:
				self.closed_at = now_datetime()

		if self.closed_at and self.opened_at and get_datetime(self.closed_at) < get_datetime(self.opened_at):
			frappe.throw(_("Closed At cannot be earlier than Opened At."))

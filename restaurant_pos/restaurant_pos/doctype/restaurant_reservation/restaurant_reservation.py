# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class RestaurantReservation(Document):
	def validate(self):
		self.validate_party_size()

		# D-191 — the timing rules live beside the floor that reads them, and
		# run here so a booking made in the desk obeys them too: no second
		# booking on a table within one turn, none after its own time.
		from restaurant_pos.utils import reservation

		reservation.validate(self)

		self.validate_table_section()
		self.validate_cancellation()

	def validate_party_size(self):
		if cint(self.party_size) < 1:
			frappe.throw(_("Party Size must be at least 1."))

	def validate_table_section(self):
		if not (self.table and self.section):
			return

		table_section = frappe.db.get_value("Restaurant Table", self.table, "section")
		if table_section != self.section:
			frappe.throw(
				_("Table {0} belongs to section {1}, not {2}.").format(
					self.table, table_section, self.section
				)
			)

	def validate_cancellation(self):
		if self.status == "cancelled" and not (self.cancel_reason or "").strip():
			frappe.throw(_("Cancel Reason is required when a reservation is cancelled."))

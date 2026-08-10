# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class POSAuditLog(Document):
	def validate(self):
		if not self.timestamp:
			self.timestamp = now_datetime()

	def on_update(self):
		# Append-only: the first write happens on insert, when there is no prior version.
		if self.get_doc_before_save():
			frappe.throw(_("POS Audit Log entries cannot be modified."), frappe.PermissionError)

	def on_trash(self):
		frappe.throw(_("POS Audit Log entries cannot be deleted."), frappe.PermissionError)

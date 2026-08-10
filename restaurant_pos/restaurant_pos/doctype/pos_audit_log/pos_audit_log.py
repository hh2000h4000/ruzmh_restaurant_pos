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

	def before_save(self):
		"""Append-only (08_Security.md §5).

		This guard must run in ``before_save``, not ``on_update``. Frappe's order
		is validate -> before_save -> db_update -> on_update, so refusing in
		``on_update`` refuses *after* the row has already been rewritten. An HTTP
		request would roll that back, but any caller that catches the exception
		and commits would leave the tampered value in place — the log would be
		immutable in name only.

		``get_doc_before_save()`` is None on insert, which is the one write an
		append-only log allows.
		"""
		if self.get_doc_before_save():
			frappe.throw(_("POS Audit Log entries cannot be modified."), frappe.PermissionError)

	def on_trash(self):
		# on_trash runs before the row is removed, so refusing here is enough.
		frappe.throw(_("POS Audit Log entries cannot be deleted."), frappe.PermissionError)

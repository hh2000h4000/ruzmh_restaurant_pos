# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class POSPrintJob(Document):
	def validate(self):
		if self.copies is None or self.copies < 1:
			self.copies = 1

		if not self.branch:
			self.branch = frappe.db.get_value("POS Printer", self.printer, "branch")

	def on_trash(self):
		"""A job in flight cannot be deleted.

		The agent may already be holding it, and deleting the row is how a
		ticket disappears without anyone being able to say whether it printed.
		"""
		if self.status == "claimed":
			frappe.throw(_("This job is with the agent right now. Wait for it to report back."))


def on_doctype_update():
	"""The three reads that run all day (`D-405`).

	Every poll asks for one agent's waiting jobs, the minute sweep asks for
	jobs by state and age, and a reprint asks for the copies of one paper. With
	no index each of those read the whole table — ninety days of every ticket.
	"""
	frappe.db.add_index("POS Print Job", ["agent", "status"])
	frappe.db.add_index("POS Print Job", ["status", "creation"])
	frappe.db.add_index("POS Print Job", ["reference_name", "reference_doctype"])

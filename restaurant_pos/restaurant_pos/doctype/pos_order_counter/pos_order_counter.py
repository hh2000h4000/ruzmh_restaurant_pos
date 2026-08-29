# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class POSOrderCounter(Document):
	"""The last short number handed out in one branch, for one stretch of time.

	One row per branch and period, named after both, so the row a till has to
	lock is found without a search and two tills cannot create rival counters
	for the same day (FR-2.10).
	"""

	def autoname(self):
		self.name = f"{self.branch}-{self.period_key}"

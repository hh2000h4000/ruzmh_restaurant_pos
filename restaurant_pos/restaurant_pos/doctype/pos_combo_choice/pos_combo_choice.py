# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class POSComboChoice(Document):
	"""One choice a combo asks — «Drink», «Extras» — with how many to pick (`D-290`).

	Square's combo option has a number of required selections; Toast's group a
	minimum and a maximum. A minimum of 0 is optional, a maximum above 1 is a
	pick of several, and 0 as the maximum is no limit.
	"""

	def validate(self):
		low, high = cint(self.min_selections), cint(self.max_selections)
		if low < 0 or high < 0:
			frappe.throw(_("Selection limits cannot be negative."))
		if high and low > high:
			frappe.throw(_("Min Selections cannot be greater than Max Selections."))

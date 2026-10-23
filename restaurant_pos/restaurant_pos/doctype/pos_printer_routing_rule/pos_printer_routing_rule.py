# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from restaurant_pos.utils.terminal_branch import branch_of


class POSPrinterRoutingRule(Document):
	def validate(self):
		self.validate_target_specificity()
		self.validate_priority()
		self.validate_branch()

	def validate_target_specificity(self):
		if self.item and self.item_group:
			frappe.throw(_("Set either Item or Item Group on a routing rule, not both."))

	def validate_branch(self):
		"""A rule sends this branch's lines to this branch's station, on this branch's tills (`D-363`)."""
		station = frappe.db.get_value("Production Center", self.production_center, "branch")
		if station and station != self.branch:
			frappe.throw(
				_("Station {0} belongs to {1}; a rule of {2} cannot send to it.").format(
					self.production_center, station, self.branch
				)
			)
		if self.pos_profile:
			till = branch_of(self.pos_profile)
			if till and till != self.branch:
				frappe.throw(
					_("Terminal {0} belongs to {1}; a rule of {2} cannot name it.").format(
						self.pos_profile, till, self.branch
					)
				)

	def validate_priority(self):
		if cint(self.priority) < 0:
			frappe.throw(_("Priority cannot be negative."))

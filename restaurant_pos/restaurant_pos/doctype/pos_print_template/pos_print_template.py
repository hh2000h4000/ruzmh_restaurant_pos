# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class POSPrintTemplate(Document):
	def validate(self):
		self.validate_single_default()

	def validate_single_default(self):
		"""Two defaults for the same type and width is a coin toss at the till.

		The one that wins would be whichever the query returned first, which
		changes when either document is edited — so the receipt would change
		shape for no reason anybody could trace.
		"""
		if not self.is_default:
			return

		# An unset Link reaches the database as NULL from one path and "" from
		# another. "not set" compiles to an ifnull() and catches both; an
		# `in ["", None]` would silently miss the NULL rows, because SQL never
		# matches NULL inside IN.
		branch = self.branch if self.branch else ("is", "not set")
		clash = frappe.db.get_value(
			"POS Print Template",
			{
				"template_type": self.template_type,
				"paper_width": self.paper_width,
				"branch": branch,
				"is_default": 1,
				"name": ("!=", self.name),
			},
			"name",
		)
		if clash:
			frappe.throw(
				_("{0} is already the default {1} template for {2} paper.").format(
					clash, self.template_type, self.paper_width
				)
			)

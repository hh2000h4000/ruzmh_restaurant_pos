# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt


class POSModifierGroup(Document):
	def validate(self):
		self.validate_options()
		self.validate_selection_limits()

	def validate_options(self):
		if not self.modifier_options:
			frappe.throw(_("At least one modifier option is required."))

		seen = set()
		for row in self.modifier_options:
			key = (row.title or "").strip().lower()
			if key in seen:
				frappe.throw(_("Row #{0}: Option '{1}' is listed more than once.").format(row.idx, row.title))
			seen.add(key)

			if row.price_effect == "none":
				row.price_amount = 0
			elif flt(row.price_amount) < 0:
				frappe.throw(_("Row #{0}: Price Amount cannot be negative.").format(row.idx))

			self.validate_item(row)

	def validate_item(self, row):
		"""An option's item is sold under the dish, or left out of its recipe (`D-284`).

		**Sold** is an ordinary line on the bill, so it must be something ERPNext
		will sell — it refuses a non-sales item at the till, mid-payment, where
		nobody can fix it. And a sold item cannot take money *off* the dish: a
		line at a negative price is not a sale.
		"""
		if not row.stock_item:
			row.item_effect = None
			return

		row.item_effect = row.item_effect or "sell"
		if row.item_effect != "sell":
			return

		if row.price_effect == "subtract":
			frappe.throw(
				_("Row #{0}: An option that sells an item cannot take money off the dish.").format(row.idx)
			)

		sellable = frappe.db.get_value("Item", row.stock_item, ["is_sales_item", "disabled"], as_dict=True)
		if not sellable or not sellable.is_sales_item or sellable.disabled:
			frappe.throw(
				_("Row #{0}: {1} is not an enabled sales item, so the till could not sell it.").format(
					row.idx, row.stock_item
				)
			)

	def validate_selection_limits(self):
		active_options = [row for row in self.modifier_options if row.is_active]
		defaults = [row for row in active_options if row.is_default]

		if self.selection_type == "single":
			self.min_selections = 1 if self.is_required else 0
			self.max_selections = 1
			if len(defaults) > 1:
				frappe.throw(_("A single-selection group can have only one default option."))
			return

		min_selections = cint(self.min_selections)
		max_selections = cint(self.max_selections)

		if min_selections < 0 or max_selections < 0:
			frappe.throw(_("Selection limits cannot be negative."))

		if self.is_required and min_selections < 1:
			frappe.throw(_("A required group must allow at least one selection."))

		if max_selections and min_selections > max_selections:
			frappe.throw(_("Min Selections cannot be greater than Max Selections."))

		if max_selections > len(active_options):
			frappe.throw(
				_("Max Selections cannot exceed the {0} active options.").format(len(active_options))
			)

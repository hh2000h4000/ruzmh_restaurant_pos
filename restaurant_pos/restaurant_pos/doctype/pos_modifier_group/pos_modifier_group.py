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
		"""An option's stock item is added under the dish, or left out of its recipe (`D-284`).

		**The price says which, and the manager is asked only when it cannot**
		(the owner's point: a question with one right answer is filler). An
		option that raises the price adds something; one that lowers it leaves
		something out. At no change of price both happen — «extra sauce, free»
		and «no onion» — so there, and only there, the answer is required.

		**Added** is an ordinary line on the bill, so it must be something ERPNext
		will sell — it refuses a non-sales item at the till, mid-payment, where
		nobody can fix it.
		"""
		if not row.stock_item:
			row.item_effect = None
			return

		if row.price_effect == "add":
			row.item_effect = "sell"
		elif row.price_effect == "subtract":
			row.item_effect = "remove"
		elif row.item_effect not in ("sell", "remove"):
			frappe.throw(
				_("Row #{0}: The price does not change, so say whether {1} is added or left out.").format(
					row.idx, row.stock_item
				)
			)

		if row.item_effect != "sell":
			return

		self.validate_quantity(row)

		sellable = frappe.db.get_value("Item", row.stock_item, ["is_sales_item", "disabled"], as_dict=True)
		if not sellable or not sellable.is_sales_item or sellable.disabled:
			frappe.throw(
				_("Row #{0}: {1} is not an enabled sales item, so the till could not sell it.").format(
					row.idx, row.stock_item
				)
			)

	def validate_quantity(self, row):
		"""How much one choice takes, in the item's stock unit (`D-284`).

		**The owner's first sale proved it was needed:** with one choice meaning
		one stock unit, «extra sauce» took a whole kilo of a sauce the recipe uses
		0.02 kg of. Foodics and Toast both carry a quantity on the mapping.
		"""
		if not flt(row.stock_qty):
			row.stock_qty = 1

		item = frappe.db.get_value("Item", row.stock_item, ["stock_uom"], as_dict=True)
		if flt(row.stock_qty) != 1 and frappe.db.exists("Product Bundle", {"new_item_code": row.stock_item}):
			# The recipe already says how much; a quantity on top would scale it twice.
			frappe.throw(
				_(
					"Row #{0}: {1} has a recipe, which already says how much it takes. Leave the quantity at 1."
				).format(row.idx, row.stock_item)
			)
		if (
			item
			and flt(row.stock_qty) != cint(row.stock_qty)
			and frappe.db.get_value("UOM", item.stock_uom, "must_be_whole_number")
		):
			frappe.throw(
				_("Row #{0}: {1} is counted in whole {2}, so the quantity must be a whole number.").format(
					row.idx, row.stock_item, item.stock_uom
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

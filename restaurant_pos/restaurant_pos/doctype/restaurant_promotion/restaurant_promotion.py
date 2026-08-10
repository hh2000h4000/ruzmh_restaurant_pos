# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate


class RestaurantPromotion(Document):
	def validate(self):
		self.validate_validity_window()
		self.validate_benefit()
		self.validate_apply_to()
		self.validate_item_scope()

	def validate_validity_window(self):
		if self.valid_from and self.valid_to and getdate(self.valid_to) < getdate(self.valid_from):
			frappe.throw(_("Valid To cannot be earlier than Valid From."))

		if bool(self.time_from) != bool(self.time_to):
			frappe.throw(_("Set both Time From and Time To, or neither."))

	def validate_benefit(self):
		if self.promotion_type == "percentage":
			if not 0 < flt(self.discount_value) <= 100:
				frappe.throw(_("A percentage discount must be between 0 and 100."))
		elif self.promotion_type == "fixed_amount":
			if flt(self.discount_value) <= 0:
				frappe.throw(_("A fixed amount discount must be greater than zero."))
		elif self.promotion_type == "free_item":
			if not self.free_item:
				frappe.throw(_("Free Item is required for a 'free_item' promotion."))

	def validate_apply_to(self):
		scoped_tables = {
			"by_order_type": "applicable_order_types",
			"by_branch": "applicable_branches",
			"by_section": "applicable_sections",
		}
		for apply_to, table_fieldname in scoped_tables.items():
			if self.apply_to == apply_to and not self.get(table_fieldname):
				frappe.throw(
					_("{0} cannot be empty when Apply To is '{1}'.").format(
						_(self.meta.get_label(table_fieldname)), apply_to
					)
				)
			if self.apply_to != apply_to:
				self.set(table_fieldname, [])

	def validate_item_scope(self):
		scoped_tables = {
			"specific_groups": "applicable_item_groups",
			"specific_items": "applicable_items",
		}
		for item_scope, table_fieldname in scoped_tables.items():
			if self.item_scope == item_scope and not self.get(table_fieldname):
				frappe.throw(
					_("{0} cannot be empty when Item Scope is '{1}'.").format(
						_(self.meta.get_label(table_fieldname)), item_scope
					)
				)
			if self.item_scope != item_scope:
				self.set(table_fieldname, [])

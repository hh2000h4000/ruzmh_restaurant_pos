# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class RestaurantOrderType(Document):
	def validate(self):
		self.validate_customer_mode()
		self.validate_unique_rows()
		self.validate_payment_methods()
		self.validate_additional_fields()

	def validate_customer_mode(self):
		"""BR-002 — a pre-set type dictates its own customer.

		The customer is required to *use* the type, not to define it: an app
		order type ships as an inactive template and the restaurant links its
		own aggregator customer before activating. Demanding it up front would
		mean shipping no template at all, since only the restaurant knows which
		receivable the money lands in.
		"""
		if self.customer_mode != "pre_set":
			self.pre_set_customer = None
			return

		if self.is_active and not self.pre_set_customer:
			frappe.throw(_("Set the Pre-set Customer before activating {0}.").format(self.title))

	def validate_unique_rows(self):
		duplicate_checks = (
			("allowed_branches", "branch"),
			("allowed_sections", "section"),
			("allowed_pos_profiles", "pos_profile"),
			("allowed_roles", "role"),
			("auto_promotions", "promotion"),
			("hidden_item_groups", "item_group"),
			("allowed_payment_methods", "payment_method"),
		)
		for table_fieldname, value_fieldname in duplicate_checks:
			seen = set()
			for row in self.get(table_fieldname) or []:
				value = row.get(value_fieldname)
				if value in seen:
					frappe.throw(_("Row #{0}: {1} is listed more than once.").format(row.idx, value))
				seen.add(value)

	def validate_payment_methods(self):
		forced = [row for row in self.allowed_payment_methods or [] if row.is_forced]
		if len(forced) > 1:
			frappe.throw(_("Only one payment method can be marked as forced."))

		defaults = [row for row in self.allowed_payment_methods or [] if row.is_default]
		if len(defaults) > 1:
			frappe.throw(_("Only one payment method can be marked as default."))

		if forced:
			# A forced method is by definition the one pre-selected at payment (BR-002).
			for row in self.allowed_payment_methods:
				row.is_default = 1 if row.is_forced else 0

	def validate_additional_fields(self):
		seen = set()
		for row in self.additional_fields or []:
			if row.field_type == "select" and not (row.field_options or "").strip():
				frappe.throw(
					_("Row #{0}: Options are required for a 'select' additional field.").format(row.idx)
				)

			key = (row.field_label or "").strip().lower()
			if key in seen:
				frappe.throw(
					_("Row #{0}: Label '{1}' is used more than once.").format(row.idx, row.field_label)
				)
			seen.add(key)

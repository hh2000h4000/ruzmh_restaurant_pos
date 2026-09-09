# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_timedelta, getdate


class RestaurantPromotion(Document):
	def validate(self):
		self.validate_validity_window()
		self.validate_benefit()
		self.validate_apply_to()
		self.validate_item_scope()

	def validate_validity_window(self):
		if self.valid_from and self.valid_to and getdate(self.valid_to) < getdate(self.valid_from):
			frappe.throw(_("Valid To cannot be earlier than Valid From."))

		self.drop_the_framework_stamp()

		if bool(self.time_from) != bool(self.time_to):
			frappe.throw(_("Set both Time From and Time To, or neither."))

	def drop_the_framework_stamp(self):
		"""An empty happy hour is empty, whatever the framework wrote in it (`D-163`).

		**Frappe fills every `Time` field with the current clock on insert** —
		`create_new.py:149`, unconditional, no `default` needed and no way to opt
		out short of editing core. So a promotion saved without a time window
		arrives holding `19:37:26` in *both* fields: a window one moment wide,
		which the engine then reads as "outside the hours" a second later. Every
		promotion a manager creates without touching those fields would be dead
		on arrival — configured, saved, listed as active, and never applying,
		with nothing anywhere to say why (`D-074`). It reached us as a test that
		failed one run in three.

		A window shorter than a minute is not a happy hour. It is that stamp, or
		a manager who typed the same time twice — and both mean the same thing:
		no window. Cleared here so the record itself says so, rather than showing
		a time nobody set. `_within_hours` holds the same line for rows already
		saved.
		"""
		if not (self.time_from and self.time_to):
			return

		start, end = get_timedelta(self.time_from), get_timedelta(self.time_to)
		if abs((end - start).total_seconds()) < 60:
			self.time_from = self.time_to = None

	def validate_benefit(self):
		if self.promotion_type == "percentage":
			if not 0 < flt(self.discount_value) <= 100:
				frappe.throw(_("A percentage discount must be between 0 and 100."))
		elif self.promotion_type == "fixed_amount":
			if flt(self.discount_value) <= 0:
				frappe.throw(_("A fixed amount discount must be greater than zero."))
		elif self.promotion_type == "free_item":
			# **Refused for the same reason as its neighbour below** (`D-169`).
			#
			# This validated, saved, and read as active — and the engine never
			# applied it, because `promotions.SUPPORTED` does not carry it. So a
			# manager could configure *any drink free with a kabsa*, watch it
			# listed among the live offers, and no guest ever got a drink.
			#
			# That is exactly the defect the `buy_x_get_y` branch below refuses
			# at the door (`D-074`), and it shipped one branch above it. One was
			# refused and the other was not, which is worse than refusing
			# neither: the record looked like the feature existed.
			#
			# A free item is not a discount but a **line**, and where the reward
			# names a group somebody has to choose which drink — a question for
			# the cashier and the guest, so it needs a screen. Until that screen
			# exists this stays shut.
			frappe.throw(
				_(
					"A free item promotion is not available yet. Use a percentage on the "
					"items it applies to, or a fixed amount off the bill."
				)
			)

		elif self.promotion_type == "buy_x_get_y":
			# The fields arrived with the reward that needed them (`D-163`,
			# `D-173`). Both are required, and both have to be at least one: a
			# "buy 0" offer is free food, and a "get 0" offer is an offer that
			# gives nothing — either would save, read as active, and be somebody
			# discovering it at the till.
			if int(self.buy_qty or 0) < 1:
				frappe.throw(_("Buy Quantity must be at least one."))

			if int(self.get_qty or 0) < 1:
				frappe.throw(_("Get Free must be at least one."))

		if flt(self.min_order_amount) < 0:
			frappe.throw(_("A minimum order amount cannot be negative."))

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

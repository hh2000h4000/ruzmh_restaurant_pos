# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The home screen's list of orders still on the floor.

Refs: 06 Screen 1, 07 §3, 04 §8
"""

import frappe

from restaurant_pos.api import order as api
from restaurant_pos.tests.test_order import ITEM, OrderTestBase
from restaurant_pos.utils import order as service


class TestOpenOrders(OrderTestBase):
	def _names(self):
		return {row["name"] for row in api.get_open_orders(self.profile)}

	def test_a_new_order_appears(self):
		order = self._order()
		self.assertIn(order.name, self._names())

	def test_a_cancelled_order_does_not(self):
		order = self._order()
		service.cancel_order(order, reason="RPOS test")
		self.assertNotIn(order.name, self._names())

	def test_a_card_carries_what_the_screen_draws(self):
		"""06 Screen 1 — type, elapsed time, item count and status."""
		order = self._order()
		service.add_item(order, item=ITEM, qty=2)

		row = next(entry for entry in api.get_open_orders(self.profile) if entry["name"] == order.name)

		self.assertEqual(row["item_count"], 1)
		self.assertEqual(row["status"], order.status)
		self.assertIn("order_minutes", row)
		self.assertTrue(row["order_type_title"])
		self.assertTrue(row["order_type_title_ar"])

	def test_a_voided_line_is_not_counted(self):
		order = self._order()
		service.add_item(order, item=ITEM, qty=1)
		service.void_item(order, item_idx=1, reason="RPOS test")

		row = next(entry for entry in api.get_open_orders(self.profile) if entry["name"] == order.name)
		self.assertEqual(row["item_count"], 0)

	def test_the_oldest_order_comes_first(self):
		"""The card that has waited longest is the one that needs attention."""
		first = self._order()
		second = self._order()

		listed = [row["name"] for row in api.get_open_orders(self.profile)]
		self.assertLess(listed.index(first.name), listed.index(second.name))

	def test_an_order_from_another_terminal_is_still_listed(self):
		"""Scoped to the branch, not the till.

		An order opened on a waiter's tablet has to be payable at the counter.
		Scoping by `pos_profile` would strand it.
		"""
		other = frappe.db.get_value(
			"POS Profile",
			{"name": ("!=", self.profile), "restaurant_section": self.section},
			"name",
		)
		if not other:
			self.skipTest("this site has only one POS Profile in the section")

		order = self._order()
		listed = {row["name"] for row in api.get_open_orders(other)}
		self.assertIn(order.name, listed)

	def test_listing_does_not_scale_with_the_number_of_orders(self):
		"""04 §8 — this list refreshes on every realtime event."""
		self._order()

		calls = 0
		real_get_all = frappe.get_all

		def counting(*args, **kwargs):
			nonlocal calls
			calls += 1
			return real_get_all(*args, **kwargs)

		frappe.get_all = counting
		try:
			api.get_open_orders(self.profile)
			baseline = calls
		finally:
			frappe.get_all = real_get_all

		for _ in range(5):
			service.add_item(self._order(), item=ITEM, qty=1)

		calls = 0
		frappe.get_all = counting
		try:
			api.get_open_orders(self.profile)
			after = calls
		finally:
			frappe.get_all = real_get_all

		self.assertEqual(after, baseline, "get_open_orders issued more queries for more orders")

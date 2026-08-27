# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Changing a line's quantity.

Refs: FR-2.2, BR-013, 06 Screen 3
"""

import frappe

from restaurant_pos.api import order as api
from restaurant_pos.tests.test_order import ITEM, OrderTestBase
from restaurant_pos.utils import order as service


class TestSetItemQty(OrderTestBase):
	def test_the_line_and_the_order_both_follow(self):
		order = self._order()
		service.add_item(order, item=ITEM, qty=1)

		service.set_item_qty(order, item_idx=1, qty=3)

		self.assertEqual(order.items[0].qty, 3)
		self.assertEqual(order.items[0].amount, 75)
		self.assertEqual(order.subtotal, 75)

	def test_zero_is_refused(self):
		"""Removing a line is a void, with a reason; it is not a quantity."""
		order = self._order()
		service.add_item(order, item=ITEM, qty=1)

		with self.assertRaises(frappe.ValidationError):
			service.set_item_qty(order, item_idx=1, qty=0)

	def test_a_line_the_kitchen_already_has_is_refused(self):
		"""BR-013 — a printed ticket cannot be edited behind the kitchen's back."""
		order = self._order()
		service.add_item(order, item=ITEM, qty=1)
		order.items[0].status = "sent"
		order.save(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			service.set_item_qty(order, item_idx=1, qty=2)

	def test_a_row_that_is_not_there_is_refused(self):
		order = self._order()

		with self.assertRaises(frappe.ValidationError):
			service.set_item_qty(order, item_idx=9, qty=2)

	def test_the_modifier_price_is_kept_per_unit_and_not_re_resolved(self):
		"""The options were priced when the line was added.

		Re-resolving them here would re-price yesterday's order at today's
		amounts; multiplying the stored per-unit figure keeps the line honest.
		"""
		order = self._order()
		row = service.add_item(order, item=ITEM, qty=1)

		# Whatever the line came to for one, two must come to exactly twice.
		one = frappe.utils.flt(row.amount)
		service.set_item_qty(order, item_idx=row.idx, qty=2)

		self.assertEqual(frappe.utils.flt(order.items[0].amount), one * 2)

	def test_replaying_the_same_queue_id_changes_nothing_twice(self):
		"""09 §8 — the offline queue may send this again."""
		import uuid

		created = api.create_order(order_type=self.order_type, pos_profile=self.profile)
		api.add_item(created["order_name"], item=ITEM, qty=1)

		queue_id = str(uuid.uuid4())
		first = api.set_item_qty(created["order_name"], item_idx=1, qty=4, queue_id=queue_id)
		second = api.set_item_qty(created["order_name"], item_idx=1, qty=4, queue_id=queue_id)

		self.assertEqual(second["qty"], first["qty"])
		self.assertTrue(second.get("already_processed"))

		order = frappe.get_doc("Restaurant Order", created["order_name"])
		self.assertEqual(order.items[0].qty, 4)

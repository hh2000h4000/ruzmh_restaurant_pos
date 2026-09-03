# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Floor plan endpoint tests.

Refs: 07 §4, BR-060, BR-061, FR-5.1
"""

import frappe

from restaurant_pos.api import table as api
from restaurant_pos.tests.test_order import ITEM, OrderTestBase
from restaurant_pos.utils import order as orders


class TestFloorPlan(OrderTestBase):
	def test_it_returns_every_table_in_the_section(self):
		plan = api.get_floor_plan(self.section)

		self.assertEqual(plan["section"]["name"], self.section)
		self.assertIn("canvas_width", plan["floor_plan"])
		self.assertTrue(plan["tables"])

	def test_an_occupied_table_carries_its_order(self):
		"""FR-5.1 — the plan shows order number, elapsed time and item count."""
		table = frappe.db.get_value("Restaurant Table", {"section": self.section, "is_active": 1}, "name")
		frappe.db.set_value("Restaurant Table", table, {"status": "available", "current_order": None})

		order = self._order(order_type=self.dine_in, table=table, cover_count=2)
		orders.add_item(order, item=ITEM, qty=2)

		plan = api.get_floor_plan(self.section)
		row = next(entry for entry in plan["tables"] if entry["name"] == table)

		self.assertEqual(row["status"], "occupied")
		# One bill, read off the list rather than off the table's own link to
		# one of them: a table may carry several (`BR-066`).
		self.assertEqual([bill["name"] for bill in row["orders"]], [order.name])
		self.assertEqual(row["orders"][0]["item_count"], 1)
		self.assertIn("minutes", row["orders"][0])

	def test_an_available_table_carries_no_order_fields(self):
		table = frappe.db.get_value(
			"Restaurant Table",
			{"section": self.section, "status": "available", "is_active": 1},
			"name",
		)
		if not table:
			self.skipTest("no free table in this section")

		plan = api.get_floor_plan(self.section)
		row = next(entry for entry in plan["tables"] if entry["name"] == table)
		self.assertEqual(row["orders"], [])

	def test_reading_the_plan_does_not_scale_with_table_count(self):
		"""04 §8 — the plan refreshes on every realtime event, in 300ms."""
		calls = 0
		real_get_all = frappe.get_all

		def counting(*args, **kwargs):
			nonlocal calls
			calls += 1
			return real_get_all(*args, **kwargs)

		frappe.get_all = counting
		try:
			api.get_floor_plan(self.section)
			baseline = calls
		finally:
			frappe.get_all = real_get_all

		for number in range(5):
			code = f"RPOS-PLAN-{number}"
			if not frappe.db.exists("Restaurant Table", {"table_number": code, "section": self.section}):
				frappe.get_doc(
					{
						"doctype": "Restaurant Table",
						"table_number": code,
						"section": self.section,
						"capacity": 2,
						"status": "available",
					}
				).insert(ignore_permissions=True)

		calls = 0
		frappe.get_all = counting
		try:
			api.get_floor_plan(self.section)
			after = calls
		finally:
			frappe.get_all = real_get_all

		self.assertEqual(after, baseline, "get_floor_plan issued more queries for more tables")

	def test_a_table_with_an_open_order_cannot_be_freed_by_hand(self):
		"""BR-061 — closing or cancelling the order is what frees a table."""
		table = frappe.db.get_value("Restaurant Table", {"section": self.section, "is_active": 1}, "name")
		frappe.db.set_value("Restaurant Table", table, {"status": "available", "current_order": None})
		self._order(order_type=self.dine_in, table=table, cover_count=2)

		with self.assertRaises(frappe.ValidationError):
			api.update_status(table, "available")

	def test_a_status_that_is_not_a_manual_one_is_refused(self):
		"""'occupied' follows from an order, never from a button."""
		table = frappe.db.get_value("Restaurant Table", {"section": self.section, "is_active": 1}, "name")

		with self.assertRaises(frappe.ValidationError):
			api.update_status(table, "occupied")

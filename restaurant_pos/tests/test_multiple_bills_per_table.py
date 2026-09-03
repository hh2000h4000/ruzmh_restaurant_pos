# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""More than one bill on a table, when the restaurant allows it (BR-066).

Two couples on a large table, or a group that asked to be billed separately
from the start. Ordinary in some restaurants and an error in others, so it is
the branch's setting and it is **off by default**: a till that quietly opened a
second bill on table four would turn one party into two, and nobody would find
out until somebody paid half of it.

The interesting half is not opening the second bill — it is letting go of the
table. Six paths release a table (paid, cancelled, transferred away, order type
changed) and every one of them used to say "available, no order". With two
bills that is wrong five times out of six: the table is still occupied by
whoever is left, and freeing it puts an empty seat on the floor plan while
people are still eating at it. So the question is asked in `release_table`,
which they all already pass through (`D-058`).

Refs: BR-061, BR-066, FR-5.2, D-058
"""

import frappe

from restaurant_pos.tests.test_order import BRANCH, ITEM, OrderTestBase
from restaurant_pos.utils import order as service
from restaurant_pos.utils import payment


class BillsOnOneTable(OrderTestBase):
	def setUp(self):
		self.allowed = frappe.db.get_value("Branch", BRANCH, "allow_multiple_orders_per_table")
		self.table = frappe.db.get_value(
			"Restaurant Table", {"section": self.section, "is_active": 1}, "name"
		)
		self._free_the_table()

	def tearDown(self):
		frappe.db.set_value("Branch", BRANCH, "allow_multiple_orders_per_table", self.allowed)
		self._free_the_table()
		frappe.db.commit()

	def _free_the_table(self) -> None:
		"""Cancel whatever is on it, so one test cannot seat the next one."""
		frappe.set_user("Administrator")
		for name in service.open_orders_on(self.table):
			frappe.db.set_value("Restaurant Order", name, "status", "cancelled")
		service.set_table_status(self.table, "available", None)
		frappe.db.commit()

	def _allow(self, allowed: bool) -> None:
		frappe.db.set_value("Branch", BRANCH, "allow_multiple_orders_per_table", 1 if allowed else 0)
		frappe.clear_cache(doctype="Branch")

	def _seat(self):
		return self._order(order_type=self.dine_in, table=self.table, cover_count=2)

	# ------------------------------------------------------------------ #

	def test_off_by_default_a_table_takes_one_bill(self):
		self._allow(False)
		self._seat()

		with self.assertRaises(frappe.ValidationError):
			self._seat()

	def test_on_the_table_takes_a_second_bill(self):
		self._allow(True)
		first = self._seat()
		second = self._seat()

		self.assertNotEqual(first.name, second.name)
		self.assertEqual(service.open_orders_on(self.table), [first.name, second.name])

	def test_paying_one_bill_leaves_the_table_occupied(self):
		"""The failure this was written for: the party that is still eating
		would have had their table shown as free the moment the other pair
		settled."""
		self._allow(True)
		first = self._seat()
		second = self._seat()

		service.add_item(first, item=ITEM, qty=1)
		first.save(ignore_permissions=True)
		first.reload()
		payment.process_payment(first, payments=[{"method": "Cash", "amount": float(first.total_amount)}])

		state = frappe.db.get_value(
			"Restaurant Table", self.table, ["status", "current_order"], as_dict=True
		)
		self.assertEqual(state.status, "occupied")
		self.assertEqual(state.current_order, second.name)

	def test_paying_the_last_bill_sends_the_table_for_cleaning(self):
		self._allow(True)
		only = self._seat()
		service.add_item(only, item=ITEM, qty=1)
		only.save(ignore_permissions=True)
		only.reload()

		payment.process_payment(only, payments=[{"method": "Cash", "amount": float(only.total_amount)}])

		self.assertEqual(frappe.db.get_value("Restaurant Table", self.table, "status"), "cleaning")

	def test_cancelling_one_of_two_leaves_the_table_occupied(self):
		self._allow(True)
		first = self._seat()
		second = self._seat()

		service.cancel_order(first, reason="غيّروا رأيهم")

		state = frappe.db.get_value(
			"Restaurant Table", self.table, ["status", "current_order"], as_dict=True
		)
		self.assertEqual(state.status, "occupied")
		self.assertEqual(state.current_order, second.name)

	def test_a_table_cannot_be_freed_by_hand_while_a_bill_is_open(self):
		"""The manual override must ask the orders, not the table's own link to
		one of them."""
		from restaurant_pos.api.table import update_status

		self._allow(True)
		self._seat()
		self._seat()

		with self.assertRaises(frappe.ValidationError):
			update_status(self.table, "available")

	def test_the_floor_plan_shows_both_bills(self):
		"""A plan that showed only the first would hide the other party's food
		and their money."""
		from restaurant_pos.api.table import get_floor_plan

		self._allow(True)
		first = self._seat()
		second = self._seat()
		service.add_item(first, item=ITEM, qty=2)
		first.save(ignore_permissions=True)

		plan = get_floor_plan(self.section)
		table = next(row for row in plan["tables"] if row["name"] == self.table)

		self.assertEqual([bill["name"] for bill in table["orders"]], [first.name, second.name])
		# Lines, not plates: `item_count` has always counted rows, and two of
		# the same dish is one row. What matters here is that the count belongs
		# to the bill that ordered it and not to the table.
		self.assertEqual(table["orders"][0]["item_count"], 1)
		self.assertEqual(table["orders"][1]["item_count"], 0)

	def test_an_empty_table_reports_no_bills(self):
		from restaurant_pos.api.table import get_floor_plan

		plan = get_floor_plan(self.section)
		table = next(row for row in plan["tables"] if row["name"] == self.table)
		self.assertEqual(table["orders"], [])

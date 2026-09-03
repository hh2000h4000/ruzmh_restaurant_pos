# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Seating an order that already exists.

A cashier rings up a few items and *then* decides where the customer sits. Until
this existed a table could only be attached when the order was created, so
tapping a table with a bill in hand either abandoned the bill or opened a second
one.

Moving a seated order is the other half: that is what `can_transfer_table` has
always been for, and two bills swapping tables is how a customer is handed
somebody else's food.

Refs: BR-061, FR-2.1a, D-040
"""

import frappe

from restaurant_pos.tests.test_order import OrderTestBase, free_table
from restaurant_pos.utils import order as service


class SeatingBase(OrderTestBase):
	def _free_table(self, skip: str | None = None) -> str:
		table = frappe.db.get_value(
			"Restaurant Table",
			{"section": self.section, "is_active": 1, "name": ("!=", skip or "")},
			"name",
		)
		return free_table(table)


class TestSeatingAnOpenOrder(SeatingBase):
	def test_an_order_with_items_keeps_them(self):
		"""The whole point: the bill is seated, not replaced."""
		order = self._order()
		service.add_item(order, item=self.item, qty=2)
		before = order.total_amount
		table = self._free_table()

		service.seat_order(order, table=table)

		self.assertEqual(order.table, table)
		self.assertEqual(len(order.items), 1)
		self.assertEqual(order.total_amount, before)

	def test_the_table_is_taken(self):
		order = self._order()
		table = self._free_table()

		service.seat_order(order, table=table)

		self.assertEqual(frappe.db.get_value("Restaurant Table", table, "status"), "occupied")
		self.assertEqual(frappe.db.get_value("Restaurant Table", table, "current_order"), order.name)

	def test_the_hall_follows_the_table(self):
		"""D-040 — the section is what tells the kitchen where to carry it."""
		order = self._order()
		table = self._free_table()

		service.seat_order(order, table=table)

		self.assertEqual(order.section, frappe.db.get_value("Restaurant Table", table, "section"))

	def test_an_occupied_table_is_refused(self):
		table = self._free_table()
		first = self._order()
		service.seat_order(first, table=table)

		second = self._order()
		with self.assertRaises(frappe.ValidationError):
			service.seat_order(second, table=table)

	def test_seating_the_same_table_twice_changes_nothing(self):
		order = self._order()
		table = self._free_table()
		service.seat_order(order, table=table)

		outcome = service.seat_order(order, table=table)

		self.assertFalse(outcome["changed"])

	def test_a_closed_order_is_not_seated(self):
		order = self._order()
		service.add_item(order, item=self.item, qty=1)
		frappe.db.set_value("Restaurant Order", order.name, "status", "closed")
		order.reload()

		with self.assertRaises(frappe.ValidationError):
			service.seat_order(order, table=self._free_table())


class TestMovingASeatedOrder(SeatingBase):
	def test_the_old_table_is_freed(self):
		order = self._order()
		first = self._free_table()
		service.seat_order(order, table=first)
		second = self._free_table(skip=first)

		service.seat_order(order, table=second)

		self.assertEqual(order.table, second)
		self.assertEqual(frappe.db.get_value("Restaurant Table", first, "status"), "available")
		self.assertIsNone(frappe.db.get_value("Restaurant Table", first, "current_order"))
		self.assertEqual(frappe.db.get_value("Restaurant Table", second, "current_order"), order.name)

	def test_a_move_is_audited_and_a_first_seating_is_not(self):
		"""Placing a bill is routine; moving one between tables is an event."""
		order = self._order()
		first = self._free_table()

		service.seat_order(order, table=first)
		entries = frappe.get_all(
			"POS Audit Log", filters={"restaurant_order": order.name, "action_type": "table_changed"}
		)
		self.assertFalse(entries, "seating an unseated order should not be audited")

		second = self._free_table(skip=first)
		service.seat_order(order, table=second)

		entries = frappe.get_all(
			"POS Audit Log",
			filters={"restaurant_order": order.name, "action_type": "table_changed"},
			fields=["details"],
		)
		self.assertEqual(len(entries), 1)
		details = frappe.parse_json(entries[0].details)
		self.assertEqual(details["from"], first)
		self.assertEqual(details["to"], second)


class TestSeatingFillsTheGuestCount(SeatingBase):
	"""BR-064 — a type that counts guests gets a number from the table."""

	def setUp(self):
		self.original = frappe.db.get_value("Restaurant Order Type", self.order_type, "requires_cover_count")
		frappe.db.set_value("Restaurant Order Type", self.order_type, "requires_cover_count", 1)
		frappe.clear_cache(doctype="Restaurant Order Type")

	def tearDown(self):
		frappe.db.set_value("Restaurant Order Type", self.order_type, "requires_cover_count", self.original)
		frappe.clear_cache(doctype="Restaurant Order Type")

	def test_the_capacity_answers_when_nobody_has(self):
		order = self._order(cover_count=2)
		frappe.db.set_value("Restaurant Order", order.name, "cover_count", 0)
		order.reload()

		table = self._free_table()
		capacity = frappe.db.get_value("Restaurant Table", table, "capacity")

		service.seat_order(order, table=table)

		self.assertEqual(order.cover_count, capacity)

	def test_a_count_already_given_is_kept(self):
		order = self._order(cover_count=5)

		service.seat_order(order, table=self._free_table())

		self.assertEqual(order.cover_count, 5)

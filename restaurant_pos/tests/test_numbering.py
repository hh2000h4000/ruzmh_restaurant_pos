# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The short number a customer is told.

An order has two numbers and they answer different questions: `name` is the
permanent id nobody says out loud, `daily_number` is what a counter shouts. The
second restarts; the first never does, which is what keeps yesterday's 42 and
today's 42 apart.

Refs: FR-2.10, FR-2.11
"""

import frappe

from restaurant_pos.tests.test_order import BRANCH, OrderTestBase
from restaurant_pos.utils import numbering
from restaurant_pos.utils import order as service


class TestTheNumberIsShortAndClimbs(OrderTestBase):
	def test_each_order_gets_the_next_one(self):
		first = self._order()
		second = self._order()

		self.assertGreater(first.daily_number, 0)
		self.assertEqual(second.daily_number, first.daily_number + 1)

	def test_the_record_id_is_not_the_number(self):
		"""`name` is traced by; `daily_number` is spoken."""
		order = self._order()

		self.assertTrue(order.name.startswith("RO-"))
		self.assertNotEqual(str(order.daily_number), order.name)

	def test_a_new_period_starts_again_at_one(self):
		self._order()

		key = numbering.period_key("daily")
		frappe.db.delete("POS Order Counter", {"branch": BRANCH, "period_key": key})
		frappe.db.commit()

		self.assertEqual(numbering.next_order_number(branch=BRANCH, shift=None), 1)


class TestWhenTheNumberRestarts(OrderTestBase):
	def tearDown(self):
		frappe.db.set_value("Branch", BRANCH, "order_number_reset", "daily")

	def _reset_to(self, period: str) -> None:
		frappe.db.set_value("Branch", BRANCH, "order_number_reset", period)

	def test_daily_is_the_default_when_nothing_is_chosen(self):
		frappe.db.set_value("Branch", BRANCH, "order_number_reset", "")
		self.assertEqual(numbering.reset_for(BRANCH), "daily")

	def test_every_period_names_itself_differently(self):
		"""Two periods sharing a key would pool their counters."""
		keys = {period: numbering.period_key(period, shift="SHIFT-1") for period in numbering.RESET_PERIODS}
		self.assertEqual(len(set(keys.values())), len(keys), keys)

	def test_never_keeps_one_running_count(self):
		self.assertEqual(numbering.period_key("never"), "all")

	def test_a_shift_period_falls_back_to_the_day(self):
		"""An order taken with no shift must not pool with every other such order."""
		self.assertEqual(numbering.period_key("shift", shift=None), numbering.period_key("daily"))


class TestCallName(OrderTestBase):
	"""FR-2.11 — a name to shout, not a Customer to file."""

	def test_it_is_set_at_creation(self):
		order = self._order(call_name="حمزة")
		self.assertEqual(order.call_name, "حمزة")

	def test_it_is_set_afterwards(self):
		order = self._order()
		service.set_call_name(order, call_name="حمزة")
		self.assertEqual(order.call_name, "حمزة")

	def test_blank_clears_it(self):
		order = self._order(call_name="حمزة")
		service.set_call_name(order, call_name="   ")
		self.assertIsNone(order.call_name)

	def test_no_customer_record_is_created(self):
		"""The whole point: a name written down is not a person filed."""
		before = frappe.db.count("Customer")
		order = self._order(call_name="حمزة")

		self.assertIsNone(order.customer)
		self.assertEqual(frappe.db.count("Customer"), before)

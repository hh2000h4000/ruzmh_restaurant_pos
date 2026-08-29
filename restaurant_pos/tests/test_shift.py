# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Opening and closing a shift.

The rule that matters most here is D-029: a delivery platform has already taken
the customer's money, so it must never be counted into the cash a drawer is
expected to hold. Get that wrong and every shift shows a shortfall the size of
the day's app orders, which teaches the cashier that the variance figure means
nothing.

Refs: FR-8.1..8.3, BR-040..BR-045, D-029
"""

import frappe

from restaurant_pos.tests.test_order import BRANCH, OrderTestBase
from restaurant_pos.utils import shift as service


class ShiftTestBase(OrderTestBase):
	def setUp(self):
		self.settlement = frappe.db.get_value("Branch", BRANCH, "settlement_required")
		self.shift_type = frappe.db.get_value("Branch", BRANCH, "shift_type")

	def tearDown(self):
		frappe.db.set_value(
			"Branch",
			BRANCH,
			{"settlement_required": self.settlement, "shift_type": self.shift_type or "single"},
		)
		# The suite's other modules expect the terminal to be selling.
		from restaurant_pos.tests.test_order import _ensure_shift

		_ensure_shift(self.profile)

	def _fresh_shift(self) -> str:
		"""Close whatever is open, then open one this test owns."""
		for name in frappe.get_all(
			"Restaurant Shift", filters={"branch": BRANCH, "status": "open"}, pluck="name"
		):
			frappe.db.set_value("Restaurant Shift", name, "status", "closed")

		return service.open_shift(pos_profile=self.profile)["shift"]


class TestOpening(ShiftTestBase):
	def test_a_terminal_with_no_shift_says_so(self):
		for name in frappe.get_all(
			"Restaurant Shift", filters={"branch": BRANCH, "status": "open"}, pluck="name"
		):
			frappe.db.set_value("Restaurant Shift", name, "status", "closed")
		frappe.db.set_value("POS Profile", self.profile, "restaurant_shift", None)

		self.assertFalse(service.shift_state(self.profile)["open"])

	def test_opening_points_the_terminal_at_it(self):
		"""BR-044 — the terminal cannot sell until this is true."""
		name = self._fresh_shift()

		self.assertEqual(frappe.db.get_value("POS Profile", self.profile, "restaurant_shift"), name)
		self.assertTrue(service.shift_state(self.profile)["open"])

	def test_a_single_shift_branch_joins_rather_than_multiplies(self):
		"""BR-041 — one day, one shift, several cashiers under it."""
		frappe.db.set_value("Branch", BRANCH, "shift_type", "single")
		first = self._fresh_shift()

		again = service.open_shift(pos_profile=self.profile)

		self.assertTrue(again["joined"])
		self.assertEqual(again["shift"], first)

	def test_a_credit_float_is_refused_quietly(self):
		"""A float on a platform method would inflate a drawer that holds nothing."""
		self._fresh_shift()
		self.assertEqual(service._clean_floats({"Cash": 200, "Jahez": 500}), {"Cash": 200.0})

	def test_an_unknown_method_is_refused_loudly(self):
		with self.assertRaises(frappe.ValidationError):
			service._clean_floats({"Nonesuch": 100})


class TestTheReport(ShiftTestBase):
	def test_it_counts_the_orders_of_this_shift(self):
		name = self._fresh_shift()
		self._order()
		self._order()

		report = service.summarise(name)

		self.assertEqual(report["orders"]["total"], 2)
		self.assertEqual(report["orders"]["still_open"], 2)
		self.assertEqual(report["orders"]["closed"], 0)

	def test_an_opening_float_is_expected_in_the_drawer(self):
		for existing in frappe.get_all(
			"Restaurant Shift", filters={"branch": BRANCH, "status": "open"}, pluck="name"
		):
			frappe.db.set_value("Restaurant Shift", existing, "status", "closed")

		name = service.open_shift(pos_profile=self.profile, opening_floats={"Cash": 200})["shift"]
		report = service.summarise(name)

		cash = next(row for row in report["by_method"] if row["method"] == "Cash")
		self.assertEqual(cash["opening"], 200.0)
		self.assertEqual(cash["expected"], 200.0)
		self.assertEqual(report["till_expected"], 200.0)


class TestClosing(ShiftTestBase):
	def test_an_open_order_blocks_the_close(self):
		name = self._fresh_shift()
		self._order()

		with self.assertRaises(frappe.ValidationError):
			service.close_shift(shift_name=name)

	def test_a_manager_may_close_over_it(self):
		name = self._fresh_shift()
		self._order()

		outcome = service.close_shift(shift_name=name, force=True)

		self.assertEqual(frappe.db.get_value("Restaurant Shift", name, "status"), "closed")
		self.assertEqual(outcome["shift"], name)

	def test_closing_stops_the_terminal_selling(self):
		"""BR-044 — a till pointed at a closed shift must refuse the next order."""
		name = self._fresh_shift()

		service.close_shift(shift_name=name, force=True)

		self.assertIsNone(frappe.db.get_value("POS Profile", self.profile, "restaurant_shift"))

	def test_a_closed_shift_cannot_be_closed_again(self):
		name = self._fresh_shift()
		service.close_shift(shift_name=name, force=True)

		with self.assertRaises(frappe.ValidationError):
			service.close_shift(shift_name=name, force=True)

	def test_without_settlement_there_is_nothing_to_explain(self):
		"""BR-042 — a shop that does not count has no difference to account for."""
		frappe.db.set_value("Branch", BRANCH, "settlement_required", 0)
		name = self._fresh_shift()

		outcome = service.close_shift(shift_name=name, force=True)

		self.assertFalse(outcome["settlement"]["settlement_required"])
		self.assertEqual(outcome["settlement"]["variance"], 0.0)

	def test_a_difference_demands_a_reason(self):
		frappe.db.set_value("Branch", BRANCH, "settlement_required", 1)
		for existing in frappe.get_all(
			"Restaurant Shift", filters={"branch": BRANCH, "status": "open"}, pluck="name"
		):
			frappe.db.set_value("Restaurant Shift", existing, "status", "closed")
		name = service.open_shift(pos_profile=self.profile, opening_floats={"Cash": 200})["shift"]

		with self.assertRaises(frappe.ValidationError):
			service.close_shift(shift_name=name, counted={"Cash": 190}, force=True)

	def test_the_difference_is_recorded_with_its_reason(self):
		frappe.db.set_value("Branch", BRANCH, "settlement_required", 1)
		for existing in frappe.get_all(
			"Restaurant Shift", filters={"branch": BRANCH, "status": "open"}, pluck="name"
		):
			frappe.db.set_value("Restaurant Shift", existing, "status", "closed")
		name = service.open_shift(pos_profile=self.profile, opening_floats={"Cash": 200})["shift"]

		outcome = service.close_shift(
			shift_name=name, counted={"Cash": 190}, variance_reason="نقص في الصرافة", force=True
		)

		self.assertEqual(outcome["settlement"]["variance"], -10.0)
		self.assertEqual(frappe.db.get_value("Restaurant Shift", name, "variance_reason"), "نقص في الصرافة")

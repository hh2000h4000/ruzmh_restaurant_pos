# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The business day, and the tills that work inside it.

Two rules carry the weight here.

**Credit never enters the count** (D-029, D-046). A delivery platform already
took the customer's money, so it must not be counted into the cash a drawer is
expected to hold — otherwise every close shows a shortfall the size of the day's
app orders and the variance figure stops meaning anything.

**The two levels are separate** (D-047). A till session is one cashier and one
drawer; a business day is the branch. Closing one is not closing the other.

Refs: FR-8.1..8.3, BR-040..BR-045, D-029, D-046, D-047
"""

import frappe

from restaurant_pos.tests.test_order import BRANCH, OrderTestBase
from restaurant_pos.utils import shift as service


class ShiftTestBase(OrderTestBase):
	def setUp(self):
		self.settlement = frappe.db.get_value("Branch", BRANCH, "settlement_required")
		self.shift_type = frappe.db.get_value("Branch", BRANCH, "shift_type")
		self._clear()

	def tearDown(self):
		frappe.db.set_value(
			"Branch",
			BRANCH,
			{"settlement_required": self.settlement, "shift_type": self.shift_type or "single"},
		)
		self._clear()
		# The suite's other modules expect the terminal to be selling.
		from restaurant_pos.tests.test_order import _ensure_shift

		_ensure_shift(self.profile)

	def _clear(self) -> None:
		"""Leave no open day or drawer behind for the next test to trip over."""
		for name in frappe.get_all(
			"POS Opening Entry", filters={"pos_profile": self.profile, "status": "Open"}, pluck="name"
		):
			frappe.db.set_value("POS Opening Entry", name, "status", "Closed")

		for name in frappe.get_all(
			"Restaurant Shift", filters={"branch": BRANCH, "status": "open"}, pluck="name"
		):
			frappe.db.set_value("Restaurant Shift", name, "status", "closed")


class TestOpening(ShiftTestBase):
	def test_a_terminal_with_nothing_open_says_so(self):
		frappe.db.set_value("POS Profile", self.profile, "restaurant_shift", None)

		state = service.shift_state(self.profile)

		self.assertFalse(state["day"]["open"])
		self.assertFalse(state["till"]["open"])

	def test_taking_the_drawer_opens_the_day_too(self):
		"""One button in the morning, not two (FR-8.1)."""
		outcome = service.open_till(pos_profile=self.profile)

		state = service.shift_state(self.profile)
		self.assertTrue(state["day"]["open"])
		self.assertTrue(state["till"]["open"])
		self.assertEqual(state["day"]["shift"], outcome["shift"])

	def test_the_terminal_is_pointed_at_the_day(self):
		"""BR-044 — the terminal cannot sell until this is true."""
		outcome = service.open_till(pos_profile=self.profile)

		self.assertEqual(
			frappe.db.get_value("POS Profile", self.profile, "restaurant_shift"), outcome["shift"]
		)

	def test_the_till_records_which_day_it_belongs_to(self):
		"""D-047 — ERPNext has no business day, so we give its entry one."""
		outcome = service.open_till(pos_profile=self.profile)

		self.assertEqual(
			frappe.db.get_value("POS Opening Entry", outcome["entry"], "rpos_restaurant_shift"),
			outcome["shift"],
		)

	def test_a_second_day_is_never_opened(self):
		"""Two days would split one day of takings across two reports."""
		first = service.open_day(pos_profile=self.profile)

		again = service.open_day(pos_profile=self.profile)

		self.assertTrue(again["joined"])
		self.assertEqual(again["shift"], first["shift"])

	def test_a_single_drawer_branch_shares_it(self):
		"""BR-041 — one drawer, and the next cashier finds it rather than a lock."""
		frappe.db.set_value("Branch", BRANCH, "shift_type", "single")
		first = service.open_till(pos_profile=self.profile)

		again = service.open_till(pos_profile=self.profile)

		self.assertTrue(again["joined"])
		self.assertEqual(again["entry"], first["entry"])

	def test_a_credit_float_is_refused_quietly(self):
		"""A float on a platform method would inflate a drawer that holds nothing."""
		self.assertEqual(service._clean_floats({"Cash": 200, "Jahez": 500}), {"Cash": 200.0})

	def test_an_unknown_method_is_refused_loudly(self):
		with self.assertRaises(frappe.ValidationError):
			service._clean_floats({"Nonesuch": 100})


class TestTheDrawer(ShiftTestBase):
	def test_the_opening_float_is_expected_in_it(self):
		outcome = service.open_till(pos_profile=self.profile, opening_floats={"Cash": 200})

		report = service.summarise_till(outcome["entry"])

		cash = next(row for row in report["by_method"] if row["method"] == "Cash")
		self.assertEqual(cash["opening"], 200.0)
		self.assertEqual(cash["expected"], 200.0)
		self.assertEqual(report["till_expected"], 200.0)

	def test_closing_it_writes_an_erpnext_closing_entry(self):
		"""D-047 — the count belongs in ERPNext own POS reconciliation."""
		outcome = service.open_till(pos_profile=self.profile, opening_floats={"Cash": 200})

		closed = service.close_till(opening_entry=outcome["entry"])

		self.assertTrue(closed["closing_entry"])
		self.assertEqual(frappe.db.get_value("POS Closing Entry", closed["closing_entry"], "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("POS Opening Entry", outcome["entry"], "status"), "Closed")

	def test_a_closed_drawer_cannot_be_closed_again(self):
		outcome = service.open_till(pos_profile=self.profile)
		service.close_till(opening_entry=outcome["entry"])

		with self.assertRaises(frappe.ValidationError):
			service.close_till(opening_entry=outcome["entry"])

	def test_closing_the_drawer_leaves_the_day_open(self):
		"""The whole point of two levels: the next cashier keeps selling."""
		outcome = service.open_till(pos_profile=self.profile)

		service.close_till(opening_entry=outcome["entry"])

		state = service.shift_state(self.profile)
		self.assertTrue(state["day"]["open"])
		self.assertFalse(state["till"]["open"])

	def test_a_difference_demands_a_reason(self):
		frappe.db.set_value("Branch", BRANCH, "settlement_required", 1)
		outcome = service.open_till(pos_profile=self.profile, opening_floats={"Cash": 200})

		with self.assertRaises(frappe.ValidationError):
			service.close_till(opening_entry=outcome["entry"], counted={"Cash": 190})

	def test_the_difference_is_recorded(self):
		frappe.db.set_value("Branch", BRANCH, "settlement_required", 1)
		outcome = service.open_till(pos_profile=self.profile, opening_floats={"Cash": 200})

		closed = service.close_till(
			opening_entry=outcome["entry"], counted={"Cash": 190}, variance_reason="نقص في الصرافة"
		)

		self.assertEqual(closed["settlement"]["variance"], -10.0)
		row = frappe.get_all(
			"POS Closing Entry Detail",
			filters={"parent": closed["closing_entry"], "mode_of_payment": "Cash"},
			fields=["expected_amount", "closing_amount", "difference"],
		)[0]
		self.assertEqual(row.expected_amount, 200.0)
		self.assertEqual(row.closing_amount, 190.0)
		self.assertEqual(row.difference, -10.0)
		self.assertEqual(
			frappe.db.get_value("POS Closing Entry", closed["closing_entry"], "rpos_variance_reason"),
			"نقص في الصرافة",
		)

	def test_without_settlement_there_is_nothing_to_explain(self):
		"""BR-042 — a shop that does not count has no difference to account for."""
		frappe.db.set_value("Branch", BRANCH, "settlement_required", 0)
		outcome = service.open_till(pos_profile=self.profile, opening_floats={"Cash": 200})

		closed = service.close_till(opening_entry=outcome["entry"])

		self.assertFalse(closed["settlement"]["settlement_required"])
		self.assertEqual(closed["settlement"]["variance"], 0.0)


class TestEndOfDay(ShiftTestBase):
	def test_an_open_order_blocks_it(self):
		outcome = service.open_till(pos_profile=self.profile)
		self._order()

		with self.assertRaises(frappe.ValidationError):
			service.close_day(shift_name=outcome["shift"])

	def test_a_manager_may_close_over_it(self):
		outcome = service.open_till(pos_profile=self.profile)
		self._order()

		service.close_day(shift_name=outcome["shift"], force=True)

		self.assertEqual(frappe.db.get_value("Restaurant Shift", outcome["shift"], "status"), "closed")

	def test_it_sweeps_up_a_drawer_left_open(self):
		"""The cashier who went home is not coming back to count it."""
		outcome = service.open_till(pos_profile=self.profile, opening_floats={"Cash": 200})

		closed = service.close_day(shift_name=outcome["shift"], force=True)

		self.assertEqual(len(closed["closed_tills"]), 1)
		self.assertEqual(frappe.db.get_value("POS Opening Entry", outcome["entry"], "status"), "Closed")

	def test_it_stops_the_terminal_selling(self):
		"""BR-044 — a till pointed at a closed day must refuse the next order."""
		outcome = service.open_till(pos_profile=self.profile)

		service.close_day(shift_name=outcome["shift"], force=True)

		self.assertIsNone(frappe.db.get_value("POS Profile", self.profile, "restaurant_shift"))

	def test_a_closed_day_cannot_be_closed_again(self):
		outcome = service.open_till(pos_profile=self.profile)
		service.close_day(shift_name=outcome["shift"], force=True)

		with self.assertRaises(frappe.ValidationError):
			service.close_day(shift_name=outcome["shift"], force=True)

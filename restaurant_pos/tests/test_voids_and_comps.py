# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The food paid for and not paid for: voided after the kitchen, and given free (`D-288`).

The burger of `test_recipes` costs 7.50 by its recipe. Two voided after the
kitchen had them cost 15.00; two voided before it cost nothing, since nothing
was made. A free slice of cheese on each of two burgers costs what the books
say two slices cost.

Refs: D-284, D-287, D-288
"""

import frappe
from frappe.utils import flt, today

from restaurant_pos.restaurant_pos.report.voids_and_comps_cost import voids_and_comps_cost as report
from restaurant_pos.tests import test_addons
from restaurant_pos.tests.test_order import ITEM
from restaurant_pos.tests.test_recipes import COST_OF_ONE, RecipeTestBase
from restaurant_pos.utils import kitchen
from restaurant_pos.utils import order as orders

REASON = "Dropped on the floor"


class VoidsAndComps(RecipeTestBase):
	def _row(self, kind: str, item: str, reason: str = "") -> dict:
		_columns, rows, *_rest = report.execute(
			frappe._dict(from_date=today(), to_date=today(), pos_profile=self.profile)
		)
		label = report._kind_label(kind)
		return next(
			(r for r in rows if r["kind"] == label and r["item_code"] == item and r["reason"] == reason),
			{"qty": 0.0, "cost": 0.0},
		)

	def _voided(self, *, sent: bool) -> None:
		order = self._payable_order(qty=2)
		if sent:
			kitchen.send_to_kitchen(order)
			order.reload()
		orders.void_item(order, item_idx=1, reason=REASON)

	def test_a_dish_voided_after_the_kitchen_costs_its_recipe(self):
		before = self._row(report.VOIDED, ITEM, REASON)
		self._voided(sent=True)
		after = self._row(report.VOIDED, ITEM, REASON)

		self.assertEqual(after["qty"] - before["qty"], 2)
		self.assertAlmostEqual(after["cost"] - before["cost"], 2 * COST_OF_ONE, places=2)

	def test_a_dish_voided_before_the_kitchen_cost_nothing_and_is_not_listed(self):
		before = self._row(report.VOIDED, ITEM, REASON)
		self._voided(sent=False)
		after = self._row(report.VOIDED, ITEM, REASON)

		self.assertEqual(after["qty"], before["qty"])

	def test_an_item_given_free_costs_what_the_books_recorded(self):
		test_addons._group(price_effect="none", price_amount=0, item_effect="sell")
		before = self._row(report.FREE, test_addons.CHEESE)

		order = self._order()
		orders.add_item(
			order, item=ITEM, qty=2, modifiers=[{"group": test_addons.GROUP, "option": "Extra cheese"}]
		)
		order.reload()
		self._pay(order)
		after = self._row(report.FREE, test_addons.CHEESE)

		cheese_cost = next(
			rate for code, _uom, _qty, rate in test_addons.RECIPE if code == test_addons.CHEESE
		)
		self.assertEqual(after["qty"] - before["qty"], 2)
		self.assertAlmostEqual(flt(after["cost"]) - flt(before["cost"]), 2 * cheese_cost, places=2)

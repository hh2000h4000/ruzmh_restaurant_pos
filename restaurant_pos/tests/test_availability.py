# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""How many of a thing sold as it came are left, and when the till refuses one (`D-321`).

The shelf alone is wrong all day: a till sale reaches the stock ledger when its
day is posted (`D-313`). So what is left is the shelf, less what was sold since,
less what sits on bills still open — and a dish with a recipe is never counted
from its ingredients at all.
"""

import frappe

from restaurant_pos.tests.test_order import BRANCH, ITEM
from restaurant_pos.tests.test_recipes import RECIPE, RecipeTestBase
from restaurant_pos.utils import availability, posting
from restaurant_pos.utils import order as orders

WATER = "RPOS-TEST-STOCKED-BOTTLE"


class AvailabilityTestBase(RecipeTestBase):
	def setUp(self):
		super().setUp()
		self._ingredient(WATER, "Nos")
		price_list = frappe.db.get_value("POS Profile", self.profile, "selling_price_list")
		if not frappe.db.exists("Item Price", {"item_code": WATER, "price_list": price_list}):
			frappe.get_doc(
				{"doctype": "Item Price", "item_code": WATER, "price_list": price_list, "price_list_rate": 2}
			).insert(ignore_permissions=True)
		self._receive(WATER, 10, 0.5)
		self.shelf = self._left()

	def _left(self, item: str = WATER) -> float | None:
		return availability.left_in(BRANCH, self.warehouse).get(item)

	def _enforce(self, on: int = 1) -> None:
		frappe.db.set_value("Branch", BRANCH, "rpos_enforce_stock", on)
		frappe.clear_document_cache("Branch", BRANCH)
		self.addCleanup(frappe.clear_document_cache, "Branch", BRANCH)


class WhatIsLeftIsTheShelfLessWhatWasSold(AvailabilityTestBase):
	def test_a_bottle_on_an_open_bill_is_not_on_the_shelf(self):
		order = self._order()
		orders.add_item(order, item=WATER, qty=3)

		self.assertEqual(self._left(), self.shelf - 3)

	def test_and_a_line_taken_off_the_bill_is_back(self):
		order = self._order()
		orders.add_item(order, item=WATER, qty=3)
		order.reload()
		orders.remove_item(order, item_idx=order.items[0].idx)

		self.assertEqual(self._left(), self.shelf)

	def test_a_sale_counts_before_its_day_is_posted_and_once_after(self):
		order = self._order()
		orders.add_item(order, item=WATER, qty=4)
		order.reload()
		self._pay(order)
		self.assertEqual(self._left(), self.shelf - 4, "paid, not posted: the ledger has not heard")

		(batch,) = [frappe.get_doc(posting.BATCH, name) for name in posting.post_branch(BRANCH)]

		self.assertEqual(batch.status, "Posted", batch.error)
		self.assertEqual(
			self._left(), self.shelf - 4, "posted: the shelf itself is lower, and nothing is counted twice"
		)

	def test_a_dish_with_a_recipe_is_not_counted_at_all(self):
		self.assertIsNone(self._left(ITEM))

	def test_the_terminal_reads_the_same_figure(self):
		frappe.cache().delete_keys("rpos_left::")

		self.assertEqual(availability.for_terminal(self.profile).get(WATER), self.shelf)


class AnEnforcingBranchRefusesWhatItHasNotGot(AvailabilityTestBase):
	def test_more_than_is_left_is_refused_and_says_how_many_there_are(self):
		self._enforce()
		order = self._order()

		with self.assertRaises(frappe.ValidationError) as refused:
			orders.add_item(order, item=WATER, qty=self.shelf + 1)

		self.assertIn(f"{self.shelf:g}", str(refused.exception))

	def test_exactly_what_is_left_is_sold_and_the_next_one_is_sold_out(self):
		self._enforce()
		order = self._order()
		orders.add_item(order, item=WATER, qty=self.shelf)

		other = self._order()
		self.assertRaises(frappe.ValidationError, orders.add_item, other, item=WATER, qty=1)

	def test_raising_a_line_asks_only_for_the_difference(self):
		self._enforce()
		order = self._order()
		orders.add_item(order, item=WATER, qty=self.shelf - 1)
		order.reload()
		idx = order.items[0].idx

		orders.set_item_qty(order, item_idx=idx, qty=self.shelf)
		order.reload()
		self.assertRaises(
			frappe.ValidationError, orders.set_item_qty, order, item_idx=idx, qty=self.shelf + 1
		)

	def test_a_dish_is_never_refused_for_its_ingredients(self):
		"""The ledger says the beef is gone; the beef is in the fridge. A person marks the dish, not the till."""
		self._enforce()
		for code, _uom, _qty, _rate in RECIPE:
			frappe.db.set_value("Bin", {"item_code": code, "warehouse": self.warehouse}, "actual_qty", 0)

		order = self._order()
		orders.add_item(order, item=ITEM, qty=5)


class ABranchThatDoesNotEnforceRefusesNothing(AvailabilityTestBase):
	def test_it_sells_past_zero_and_the_figure_says_so(self):
		self._enforce(0)
		order = self._order()

		orders.add_item(order, item=WATER, qty=self.shelf + 2)

		self.assertEqual(self._left(), -2)

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""How many of a thing sold as it came are left, and when the till refuses one (`D-321`).

The shelf alone is wrong all day: a till sale reaches the stock ledger when its
day is posted (`D-313`). So what is left is the shelf, less what was sold since,
less what sits on bills still open — and a dish with a recipe is never counted
from its ingredients at all.
"""

import frappe

from restaurant_pos.tests import test_addons as addon_tests
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
		# The class rolls back once, at its end: each test starts with nothing marked.
		availability.start_the_day_clean(BRANCH)
		self.shelf = self._left()

	def tearDown(self):
		# **Before the base class's tearDown, which commits.** A mark or a mode
		# left standing there is on the site for every module after this one —
		# 504 tests refused a burger "sold out" by a test that had long finished.
		availability.start_the_day_clean(BRANCH)
		frappe.db.set_value("Branch", BRANCH, "rpos_enforce_stock", 0)
		frappe.db.set_single_value("Restaurant POS Settings", "low_stock_at", availability.LOW_AT)
		frappe.clear_document_cache("Branch", BRANCH)
		super().tearDown()

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


class FinishedForToday(AvailabilityTestBase):
	"""`D-322` — the cook says the soup is finished; the till believes the cook."""

	def test_a_dish_marked_finished_is_refused_in_a_branch_that_enforces_nothing(self):
		self._enforce(0)
		availability.set_sold_out(BRANCH, ITEM, True)

		order = self._order()
		with self.assertRaises(frappe.ValidationError):
			orders.add_item(order, item=ITEM, qty=1)

	def test_brought_back_it_sells_again(self):
		availability.set_sold_out(BRANCH, ITEM, True)
		self.assertEqual(availability.set_sold_out(BRANCH, ITEM, False), [])

		order = self._order()
		orders.add_item(order, item=ITEM, qty=1)

	def test_marking_twice_is_one_mark(self):
		availability.set_sold_out(BRANCH, ITEM, True)

		self.assertEqual(availability.set_sold_out(BRANCH, ITEM, True), [ITEM])

	def test_it_moves_no_stock(self):
		before = frappe.db.count("Stock Ledger Entry")

		availability.set_sold_out(BRANCH, WATER, True)

		self.assertEqual(frappe.db.count("Stock Ledger Entry"), before)
		self.assertEqual(self._left(), self.shelf)

	def test_closing_the_day_brings_everything_back(self):
		from restaurant_pos.utils import shift as shift_service

		# The bottle, not the burger: closing a day commits on the way, and a
		# mark committed on the dish every other module sells stops all of them.
		availability.set_sold_out(BRANCH, WATER, True)
		day = frappe.db.get_value("POS Profile", self.profile, "restaurant_shift")

		shift_service.close_day(shift_name=day, force=True, pos_profile=self.profile)

		self.assertEqual(availability.sold_out(BRANCH), [])

	def test_the_till_is_told_who_is_finished_and_who_is_low(self):
		frappe.cache().delete_keys("rpos_left::")
		frappe.db.set_single_value("Restaurant POS Settings", "low_stock_at", int(self.shelf))
		availability.set_sold_out(BRANCH, ITEM, True)

		told = availability.for_till(self.profile)

		self.assertEqual(told["sold_out"], [ITEM])
		self.assertEqual(told["left"].get(WATER), self.shelf)
		self.assertEqual(told["low_at"], int(self.shelf))

	def test_an_item_above_the_line_sends_no_number(self):
		frappe.cache().delete_keys("rpos_left::")
		frappe.db.set_single_value("Restaurant POS Settings", "low_stock_at", int(self.shelf) - 1)

		self.assertNotIn(WATER, availability.for_till(self.profile)["left"])

	def test_an_item_with_its_own_line_follows_it(self):
		"""`D-324` — water by the case is low at thirty; the restaurant's line is ten."""
		frappe.cache().delete_keys("rpos_left::")
		frappe.db.set_single_value("Restaurant POS Settings", "low_stock_at", 1)
		frappe.db.set_value("Item", WATER, "rpos_low_stock_at", int(self.shelf) + 20)
		self.addCleanup(frappe.db.set_value, "Item", WATER, "rpos_low_stock_at", 0)

		self.assertEqual(availability.for_till(self.profile)["left"].get(WATER), self.shelf)


class AnAddOnOffTheShelfIsCheckedLikeTheBottle(AvailabilityTestBase):
	"""`D-335` — the owner's trial sold extra cheese with the cheese at minus fourteen."""

	CHEESE_OPTION = ({"group": addon_tests.GROUP, "option": "Extra cheese"},)

	def setUp(self):
		super().setUp()
		addon_tests._group()
		frappe.db.set_value(
			"Bin", {"item_code": addon_tests.CHEESE, "warehouse": self.warehouse}, "actual_qty", 1
		)

	def test_an_enforcing_branch_refuses_the_add_on_it_has_not_got(self):
		self._enforce()
		order = self._order()

		with self.assertRaises(frappe.ValidationError):
			orders.add_item(order, item=ITEM, qty=2, modifiers=list(self.CHEESE_OPTION))

	def test_and_sells_the_one_it_has(self):
		self._enforce()
		order = self._order()

		orders.add_item(order, item=ITEM, qty=1, modifiers=list(self.CHEESE_OPTION))

	def test_the_dish_itself_is_still_not_refused_for_its_recipe(self):
		"""The recipe's own cheese is an ingredient; only the slice sold on top is a sale."""
		self._enforce()
		order = self._order()

		orders.add_item(order, item=ITEM, qty=5)

	def test_raising_the_line_asks_for_the_extra_slices_too(self):
		self._enforce()
		order = self._order()
		orders.add_item(order, item=ITEM, qty=1, modifiers=list(self.CHEESE_OPTION))
		order.reload()

		with self.assertRaises(frappe.ValidationError):
			orders.set_item_qty(order, item_idx=order.items[0].idx, qty=3)

	def test_a_branch_that_does_not_enforce_sells_it_anyway(self):
		self._enforce(0)
		order = self._order()

		orders.add_item(order, item=ITEM, qty=4, modifiers=list(self.CHEESE_OPTION))

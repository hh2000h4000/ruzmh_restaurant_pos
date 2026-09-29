# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""An add-on tied to an item is sold like any item, and the warehouse agrees (`D-284`).

The burger of `test_recipes` — bun, 0.15 kg of beef, a slice of cheese, 7.50 a
burger — with two choices on it:

- «Extra cheese», +2.00, sells a slice of cheese as a line of its own.
- «No bun» takes the bun out of the recipe.

Every figure the warehouse should show is known, so it is checked to the unit:
what left on the sale, what came back on the return, and what nothing touched.

Refs: FR-4.2, D-281, D-284
"""

import frappe
from frappe.utils import flt, today

from restaurant_pos.restaurant_pos.report.item_sales import item_sales
from restaurant_pos.tests.test_order import ITEM
from restaurant_pos.tests.test_recipes import COST_OF_ONE, RECIPE, RecipeTestBase
from restaurant_pos.utils import order as orders
from restaurant_pos.utils import returns

GROUP = "RPOS Test Extras"
CHEESE = "RPOS-TEST-CHEESE"
BUN = "RPOS-TEST-BUN"
EXTRA = 2.00

UNIT_COST = {code: rate for code, _uom, _qty, rate in RECIPE}
PER_BURGER = {code: qty for code, _uom, qty, _rate in RECIPE}


PATTY = "RPOS-TEST-PATTY"
EXTRA_PATTY = {
	"title": "Extra patty",
	"title_ar": "لحم إضافي",
	"price_effect": "add",
	"price_amount": 4.00,
	"stock_item": PATTY,
	"stock_qty": 0.15,
	"is_active": 1,
}


def _group(*extra: dict, **overrides) -> str:
	if frappe.db.exists("POS Modifier Group", GROUP):
		frappe.delete_doc("POS Modifier Group", GROUP, force=True, ignore_permissions=True)
	cheese = {
		"title": "Extra cheese",
		"title_ar": "جبنة إضافية",
		"price_effect": "add",
		"price_amount": EXTRA,
		"stock_item": CHEESE,
		"item_effect": "sell",
		"is_active": 1,
		**overrides,
	}
	no_bun = {
		"title": "No bun",
		"title_ar": "بدون خبز",
		"price_effect": "none",
		"stock_item": BUN,
		"item_effect": "remove",
		"is_active": 1,
	}
	frappe.get_doc(
		{
			"doctype": "POS Modifier Group",
			"__newname": GROUP,
			"title": GROUP,
			"title_ar": "إضافات",
			"selection_type": "multiple",
			"modifier_options": [cheese, no_bun, *extra],
		}
	).insert(ignore_permissions=True)
	return GROUP


class AnAddOnIsSoldLikeAnyItem(RecipeTestBase):
	def setUp(self):
		super().setUp()
		_group()

	def _sold_with(self, *options: str, qty: float = 2):
		order = self._order()
		orders.add_item(
			order, item=ITEM, qty=qty, modifiers=[{"group": GROUP, "option": option} for option in options]
		)
		order.reload()
		self._pay(order)
		order.reload()
		return order

	def _lines(self, invoice: str) -> list:
		return frappe.get_all(
			"Sales Invoice Item",
			filters={"parent": invoice},
			fields=["name", "item_code", "qty", "rate", "amount", "rpos_is_addon", "rpos_order_item"],
			order_by="idx",
		)

	def test_the_extra_cheese_is_its_own_line_under_the_dish_and_the_bill_is_unchanged(self):
		order = self._sold_with("Extra cheese")
		burger, cheese = self._lines(order.sales_invoice)

		self.assertEqual((burger.item_code, burger.rpos_is_addon), (ITEM, 0))
		self.assertEqual((cheese.item_code, cheese.rpos_is_addon, flt(cheese.qty)), (CHEESE, 1, 2))
		self.assertAlmostEqual(flt(cheese.rate), EXTRA, places=2)
		self.assertEqual(cheese.rpos_order_item, burger.rpos_order_item)
		# The till's line held the dish and the cheese; the two lines hold the same money.
		self.assertAlmostEqual(flt(burger.amount) + flt(cheese.amount), flt(order.items[0].amount), places=2)

	def test_the_extra_cheese_leaves_the_warehouse_on_top_of_the_recipe(self):
		order = self._sold_with("Extra cheese")

		expected = {code: flt(-2 * qty, 3) for code, qty in PER_BURGER.items()}
		expected[CHEESE] = flt(expected[CHEESE] - 2, 3)
		self.assertEqual(self._moved(order.sales_invoice), expected)

	def test_no_bun_keeps_the_bun_in_the_warehouse_and_off_the_cost(self):
		order = self._sold_with("No bun")

		moved = self._moved(order.sales_invoice)
		self.assertNotIn(BUN, moved)
		self.assertEqual(moved[CHEESE], -2)

		cost = sum(
			flt(row.incoming_rate) * flt(row.qty)
			for row in frappe.get_all(
				"Packed Item",
				filters={"parent": order.sales_invoice},
				fields=["incoming_rate", "qty"],
			)
		)
		self.assertAlmostEqual(cost, 2 * (COST_OF_ONE - UNIT_COST[BUN]), places=2)

	def test_the_report_sells_the_cheese_as_an_item_with_its_cost(self):
		def row(code):
			_columns, rows, *_rest = item_sales.execute(
				frappe._dict(from_date=today(), to_date=today(), pos_profile=self.profile, show_cost=1)
			)
			return next((r for r in rows if r.get("item_code") == code), {"qty": 0.0, "cost": 0.0})

		before = row(CHEESE)
		self._sold_with("Extra cheese")
		after = row(CHEESE)

		self.assertEqual(flt(after["qty"]) - flt(before["qty"]), 2)
		self.assertAlmostEqual(flt(after["cost"]) - flt(before["cost"]), 2 * UNIT_COST[CHEESE], places=2)

	def test_a_returned_dish_brings_its_cheese_back_and_still_leaves_the_bun_out(self):
		order = self._sold_with("Extra cheese", "No bun")

		offered = returns.returnable(order)["items"]
		self.assertEqual(len(offered), 1, "the cheese is never offered on its own")
		burger_rate = flt(self._lines(order.sales_invoice)[0].rate)
		self.assertAlmostEqual(offered[0]["rate"], burger_rate + EXTRA, places=2)

		result = returns.create_return(
			order, items=[{"row": offered[0]["row"], "qty": 1}], reason_code="goods_returned"
		)

		back = self._moved(result["credit_note"])
		self.assertNotIn(BUN, back)
		self.assertEqual(back[CHEESE], 2, "one slice from the recipe, one from the add-on")
		self.assertEqual(back["RPOS-TEST-PATTY"], flt(PER_BURGER["RPOS-TEST-PATTY"], 3))
		self.assertEqual(
			{line.item_code: flt(line.qty) for line in self._lines(result["credit_note"])},
			{ITEM: -1, CHEESE: -1},
		)

	def test_a_weighed_add_on_takes_its_quantity_and_keeps_its_price(self):
		"""The owner's first sale: «extra sauce» took a whole kilo of a 0.02 kg sauce."""
		_group(EXTRA_PATTY)

		def patty_cost():
			_columns, rows, *_rest = item_sales.execute(
				frappe._dict(from_date=today(), to_date=today(), pos_profile=self.profile, show_cost=1)
			)
			return flt(next((r for r in rows if r.get("item_code") == PATTY), {"cost": 0.0})["cost"])

		before = patty_cost()
		order = self._sold_with("Extra patty")
		line = next(line for line in self._lines(order.sales_invoice) if line.item_code == PATTY)

		# Two portions sold at 4.00 each — the money as rung, to the halala.
		self.assertEqual((flt(line.qty), flt(line.rate), flt(line.amount)), (2, 4.0, 8.0))
		# 0.15 kg a burger from the recipe, and 0.15 kg a burger from the add-on.
		self.assertEqual(self._moved(order.sales_invoice)[PATTY], flt(-4 * PER_BURGER[PATTY], 3))
		# Costed by the kilo that left, not by the portions sold.
		self.assertAlmostEqual(patty_cost() - before, 2 * 0.15 * UNIT_COST[PATTY], places=2)

	def test_an_option_with_no_item_sells_nothing_extra(self):
		frappe.db.set_value(
			"POS Modifier Option", {"parent": GROUP, "title": "Extra cheese"}, "stock_item", None
		)
		order = self._sold_with("Extra cheese")

		self.assertEqual([line.item_code for line in self._lines(order.sales_invoice)], [ITEM])


class TheOptionIsCheckedWhenSaved(RecipeTestBase):
	def _effect(self, title: str) -> str:
		return frappe.db.get_value("POS Modifier Option", {"parent": GROUP, "title": title}, "item_effect")

	def test_the_price_decides_adding_or_leaving_out(self):
		"""The owner's rule: a question with one right answer is not asked."""
		_group(price_effect="add", item_effect="remove")
		self.assertEqual(self._effect("Extra cheese"), "sell")

		_group(price_effect="subtract", item_effect="sell")
		self.assertEqual(self._effect("Extra cheese"), "remove")

	def test_at_no_change_of_price_the_answer_is_required(self):
		with self.assertRaises(frappe.ValidationError):
			_group(price_effect="none", price_amount=0, item_effect=None)

		_group(price_effect="none", price_amount=0, item_effect="sell")
		self.assertEqual(self._effect("Extra cheese"), "sell")

	def test_half_a_slice_of_a_counted_item_is_refused(self):
		if not frappe.db.get_value("UOM", "Nos", "must_be_whole_number"):
			self.skipTest("Nos is not whole-number on this site")
		with self.assertRaises(frappe.ValidationError):
			_group(stock_qty=0.5)

	def test_an_item_the_till_cannot_sell_is_refused(self):
		frappe.db.set_value("Item", CHEESE, "is_sales_item", 0)
		self.addCleanup(frappe.db.set_value, "Item", CHEESE, "is_sales_item", 1)
		with self.assertRaises(frappe.ValidationError):
			_group()

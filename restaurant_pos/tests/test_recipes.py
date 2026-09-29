# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""A dish's recipe comes out of stock when the till sells it — does it? (`D-281`).

The first question under stock and costing, asked before anything is built: a
prepared dish is not a stock item, so selling one moved nothing and cost
nothing — a burger at 100% margin. ERPNext's own answer for "one thing sold,
several things taken out" is the Product Bundle: the invoice unpacks it into
packed items and takes those from the warehouse when it updates stock.

The till's invoice is ERPNext's own Sales Invoice with `update_stock`, so the
bundle should work unchanged. This holds it to that, with a recipe whose every
figure is known: what leaves the warehouse, and what the dish cost.

Refs: D-233, D-281
"""

import frappe
from frappe.utils import flt, today

from restaurant_pos.restaurant_pos.report.item_sales import item_sales
from restaurant_pos.tests.test_order import ITEM
from restaurant_pos.tests.test_payment import PaymentTestBase
from restaurant_pos.utils import returns

#: code, stock unit, how much one burger takes, what a unit cost.
RECIPE = (
	("RPOS-TEST-BUN", "Nos", 1, 1.00),
	("RPOS-TEST-PATTY", "Kg", 0.15, 40.00),
	("RPOS-TEST-CHEESE", "Nos", 1, 0.50),
)

#: 1.00 + 0.15 * 40.00 + 0.50
COST_OF_ONE = 7.50


class RecipeTestBase(PaymentTestBase):
	"""The burger with a recipe, and every ingredient in stock (shared with `test_addons`)."""

	def setUp(self):
		super().setUp()
		self.warehouse = frappe.db.get_value("POS Profile", self.profile, "warehouse")
		self.company = frappe.db.get_value("POS Profile", self.profile, "company")
		for code, uom, _qty, rate in RECIPE:
			self._ingredient(code, uom)
			self._receive(code, 100, rate)
		self._bundle()

	def _ingredient(self, code: str, uom: str) -> None:
		if frappe.db.exists("Item", code):
			return
		if not frappe.db.exists("UOM", uom):
			frappe.get_doc({"doctype": "UOM", "uom_name": uom}).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_name": code,
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
				"stock_uom": uom,
				"is_stock_item": 1,
			}
		).insert(ignore_permissions=True)

	def _receive(self, code: str, qty: float, rate: float) -> None:
		entry = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"company": self.company,
				"items": [{"item_code": code, "qty": qty, "basic_rate": rate, "t_warehouse": self.warehouse}],
			}
		)
		entry.insert(ignore_permissions=True)
		entry.submit()

	def _bundle(self) -> None:
		_drop_bundle()
		frappe.get_doc(
			{
				"doctype": "Product Bundle",
				"new_item_code": ITEM,
				"items": [{"item_code": code, "qty": qty} for code, _uom, qty, _rate in RECIPE],
			}
		).insert(ignore_permissions=True)
		# Every other test sells this burger with no ingredients in stock, so the
		# recipe must not outlive this one — and it cannot be deleted the normal
		# way: ERPNext refuses once the item has ever been invoiced.
		self.addCleanup(_drop_bundle)

	def _sold(self, qty: float):
		order = self._payable_order(qty=qty)
		self._pay(order)
		order.reload()
		return order

	def _moved(self, voucher: str) -> dict[str, float]:
		"""What each item did in the warehouse on one document."""
		moved: dict[str, float] = {}
		for row in frappe.get_all(
			"Stock Ledger Entry",
			filters={"voucher_no": voucher, "is_cancelled": 0},
			fields=["item_code", "actual_qty"],
		):
			moved[row.item_code] = flt(moved.get(row.item_code, 0) + flt(row.actual_qty), 3)
		return moved


class TheRecipeLeavesTheWarehouse(RecipeTestBase):
	def test_each_ingredient_leaves_the_warehouse_in_its_recipe_quantity(self):
		order = self._sold(qty=2)

		moved = {
			row.item_code: flt(row.actual_qty, 3)
			for row in frappe.get_all(
				"Stock Ledger Entry",
				filters={"voucher_no": order.sales_invoice, "is_cancelled": 0},
				fields=["item_code", "actual_qty"],
			)
		}
		self.assertEqual(moved, {code: flt(-2 * qty, 3) for code, _uom, qty, _rate in RECIPE})

	def test_the_dish_costs_what_its_recipe_cost(self):
		order = self._sold(qty=2)

		cost = sum(
			flt(row.stock_value_difference)
			for row in frappe.get_all(
				"Stock Ledger Entry",
				filters={"voucher_no": order.sales_invoice, "is_cancelled": 0},
				fields=["stock_value_difference"],
			)
		)
		self.assertAlmostEqual(-cost, 2 * COST_OF_ONE, places=2)

	def _row(self) -> dict:
		"""The dish's row today — other tests sell it too, so tests compare before and after."""
		_columns, rows, *_rest = item_sales.execute(
			frappe._dict(from_date=today(), to_date=today(), pos_profile=self.profile, show_cost=1)
		)
		return next(
			(row for row in rows if row.get("item_code") == ITEM),
			{"cost": 0.0, "uncosted_qty": 0.0, "amount": 0.0},
		)

	def test_the_item_sales_report_costs_the_dish_from_its_recipe(self):
		"""The dish's own line carries no cost; its ingredients do (`D-281`)."""
		before = self._row()
		self._sold(qty=2)
		after = self._row()

		self.assertAlmostEqual(after["cost"] - before["cost"], 2 * COST_OF_ONE, places=2)
		self.assertEqual(after["uncosted_qty"], before["uncosted_qty"])
		# Food cost as the Uniform System of Accounts for Restaurants states it.
		self.assertAlmostEqual(after["cost_ratio"], after["cost"] / after["amount"] * 100, places=1)

	def test_a_refunded_dish_takes_its_recipe_cost_back(self):
		before = self._row()
		order = self._sold(qty=2)
		line = returns.returnable(order)["items"][0]["row"]
		returns.create_return(order, items=[{"row": line, "qty": 1}], reason_code="goods_returned")
		after = self._row()

		self.assertAlmostEqual(after["cost"] - before["cost"], COST_OF_ONE, places=2)
		self.assertEqual(after["uncosted_qty"], before["uncosted_qty"])

	def test_an_ingredient_with_no_cost_counts_as_nothing_and_the_rest_still_count(self):
		"""`D-282` — a bun carried at zero made the whole burger uncosted; now it costs nothing.

		The books recorded zero for it — ERPNext posts no ingredient without a
		valuation unless «Allow Zero Valuation Rate» is ticked — and IAS 2 ¶34 puts
		the carrying amount in cost of sales. So the report shows the books.
		"""
		before = self._row()
		order = self._sold(qty=2)
		# An ingredient that came into stock with no worth, as a receipt without a rate does.
		frappe.db.set_value(
			"Packed Item",
			{"parent": order.sales_invoice, "item_code": "RPOS-TEST-BUN"},
			"incoming_rate",
			0,
		)

		_columns, rows, message = item_sales.execute(
			frappe._dict(from_date=today(), to_date=today(), pos_profile=self.profile, show_cost=1)
		)
		after = next(row for row in rows if row.get("item_code") == ITEM)
		bun = next(rate for code, _uom, _qty, rate in RECIPE if code == "RPOS-TEST-BUN")

		self.assertAlmostEqual(after["cost"] - before["cost"], 2 * (COST_OF_ONE - bun), places=2)
		self.assertEqual(after["uncosted_qty"], before["uncosted_qty"])
		self.assertEqual(after["short_costed_qty"], 2)
		self.assertIn("carried at zero cost", message)


def _drop_bundle() -> None:
	frappe.db.delete("Product Bundle Item", {"parent": ITEM})
	frappe.db.delete("Product Bundle", {"name": ITEM})

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


class TheRecipeLeavesTheWarehouse(PaymentTestBase):
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

	def test_a_refunded_dish_takes_its_recipe_cost_back(self):
		before = self._row()
		order = self._sold(qty=2)
		line = returns.returnable(order)["items"][0]["row"]
		returns.create_return(order, items=[{"row": line, "qty": 1}], reason_code="goods_returned")
		after = self._row()

		self.assertAlmostEqual(after["cost"] - before["cost"], COST_OF_ONE, places=2)
		self.assertEqual(after["uncosted_qty"], before["uncosted_qty"])


def _drop_bundle() -> None:
	frappe.db.delete("Product Bundle Item", {"parent": ITEM})
	frappe.db.delete("Product Bundle", {"name": ITEM})

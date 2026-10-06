# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Actual against theoretical usage, count to count (`D-287`).

A drink counted at 100, two sold, one written off as spilled, and 96 counted at
the close. Actual usage is 4: theoretical 2, waste 1 — and one bottle nobody
can account for.

Each test sells an item of its own: the ledger is shared across the suite, and
a count only means something over entries it can see all of.

Refs: D-281, D-287
"""

import datetime

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from restaurant_pos.restaurant_pos.report.actual_vs_theoretical_usage import (
	actual_vs_theoretical_usage as report,
)
from restaurant_pos.tests.test_order import TEST_PRICE_LIST
from restaurant_pos.tests.test_payment import PaymentTestBase
from restaurant_pos.utils import order as orders
from restaurant_pos.utils import posting

COST = 2.00


class ActualAgainstTheoretical(PaymentTestBase):
	def setUp(self):
		super().setUp()
		self.warehouse = frappe.db.get_value("POS Profile", self.profile, "warehouse")
		self.company = frappe.db.get_value("POS Profile", self.profile, "company")
		self.item = f"RPOS-TEST-AVT-{frappe.generate_hash(length=6).upper()}"
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": self.item,
				"item_name": self.item,
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
				"stock_uom": "Nos",
				"is_stock_item": 1,
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": self.item,
				"price_list": TEST_PRICE_LIST,
				"price_list_rate": 5,
			}
		).insert(ignore_permissions=True)

	def _at(self, moment: datetime.datetime) -> dict:
		return {
			"set_posting_time": 1,
			"posting_date": moment.date(),
			"posting_time": moment.strftime("%H:%M:%S"),
		}

	def _count(self, qty: float, at: datetime.datetime) -> str:
		count = frappe.get_doc(
			{
				"doctype": "Stock Reconciliation",
				"company": self.company,
				"purpose": "Stock Reconciliation",
				**self._at(at),
				"items": [
					{"item_code": self.item, "warehouse": self.warehouse, "qty": qty, "valuation_rate": COST}
				],
			}
		)
		count.insert(ignore_permissions=True)
		count.submit()
		return count.name

	def _move(self, purpose: str, row: dict, at: datetime.datetime) -> None:
		entry = frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": purpose,
				"company": self.company,
				**self._at(at),
				"items": [{"item_code": self.item, **row}],
			}
		)
		entry.insert(ignore_permissions=True)
		entry.submit()

	def _spill(self, qty: float, at: datetime.datetime) -> None:
		self._move("Material Issue", {"qty": qty, "s_warehouse": self.warehouse}, at)

	def _opening(self, counted: float) -> str:
		"""A delivery first — ERPNext treats a count of an item it never held as an opening balance."""
		self._move(
			"Material Receipt",
			{"qty": 90, "basic_rate": COST, "t_warehouse": self.warehouse},
			add_to_date(now_datetime(), minutes=-30),
		)
		return self._count(counted, add_to_date(now_datetime(), minutes=-10))

	def _sell(self, qty: float) -> datetime.datetime:
		order = self._order()
		orders.add_item(order, item=self.item, qty=qty)
		order.reload()
		self._pay(order)
		order.reload()
		# The sale reaches the stock ledger when its day is posted (`D-313`), and
		# that document's time is the one the ledger orders by.
		posting.post_branch(order.branch)
		issue = posting.stock_voucher_of(order.sales_invoice)
		posted = frappe.db.get_value("Stock Entry", issue, ["posting_date", "posting_time"])
		return get_datetime(f"{posted[0]} {posted[1]}")

	def _row(self, opening: str, closing: str | None) -> dict:
		_columns, rows, *_rest = report.execute(
			frappe._dict(warehouse=self.warehouse, opening_count=opening, closing_count=closing)
		)
		return next(row for row in rows if row["item_code"] == self.item)

	def test_the_variance_is_what_the_count_found_that_sales_and_waste_do_not_explain(self):
		# The clock on the test machine steps back under load (`D-261`), so the
		# documents carry their own times around the sale's.
		opening = self._opening(100)
		sold_at = self._sell(2)
		self._spill(1, add_to_date(sold_at, seconds=1))
		closing = self._count(96, add_to_date(sold_at, seconds=2))

		row = self._row(opening, closing)

		self.assertEqual(
			{field: row[field] for field in ("opening", "sold", "waste", "closing", "actual", "variance")},
			{"opening": 100, "sold": 2, "waste": 1, "closing": 96, "actual": 4, "variance": 1},
		)
		self.assertEqual(row["variance_pct"], 50)
		self.assertAlmostEqual(row["variance_value"], COST, places=2)

	def test_without_a_closing_count_the_books_close_and_nothing_is_unexplained(self):
		opening = self._opening(100)
		self._sell(2)

		row = self._row(opening, None)

		self.assertEqual((row["sold"], row["closing"], row["variance"]), (2, 98, 0))

	def test_a_closing_count_before_the_opening_one_is_refused(self):
		late = self._opening(100)
		early = self._count(95, add_to_date(now_datetime(), minutes=-20))
		with self.assertRaises(frappe.ValidationError):
			report.execute(frappe._dict(warehouse=self.warehouse, opening_count=late, closing_count=early))

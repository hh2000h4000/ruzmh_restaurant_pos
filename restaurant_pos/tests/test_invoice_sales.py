# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Every bill, at two depths (`D-273`).

The bill carries what a restaurant reads it by — its daily number, how it was
paid — the item view's lines add up to the bill, and a refund is on the page,
negative, naming the bill it reverses.

Refs: FR-11.2, D-273
"""

import frappe
from frappe.utils import flt, today

from restaurant_pos.restaurant_pos.report.invoice_sales import invoice_sales as report
from restaurant_pos.tests.test_payment import CASH, PaymentTestBase
from restaurant_pos.utils import returns

REASON = "goods_returned"


class TestTheBills(PaymentTestBase):
	def _rows(self, view: str) -> list[dict]:
		_columns, rows = report.execute({"from_date": today(), "to_date": today(), "view": view})
		return rows

	def _sold(self, qty: float = 2):
		order = self._payable_order(qty=qty)
		self._pay(order)
		order.reload()
		return order

	def test_a_bill_carries_its_number_and_how_it_was_paid(self):
		order = self._sold()

		row = next(row for row in self._rows("invoice") if row.get("invoice") == order.sales_invoice)
		self.assertEqual(str(row["number"]), str(order.daily_number))
		self.assertIn(CASH, row["paid_by"])
		self.assertAlmostEqual(
			row["total"],
			flt(frappe.db.get_value("Sales Invoice", order.sales_invoice, "grand_total")),
			places=2,
		)

	def test_the_item_lines_add_up_to_the_bill(self):
		order = self._sold()
		invoice = frappe.get_doc("Sales Invoice", order.sales_invoice)

		lines = [row for row in self._rows("item") if row.get("invoice") == order.sales_invoice]
		self.assertEqual(len(lines), len(invoice.items))
		self.assertAlmostEqual(sum(line["amount"] for line in lines), flt(invoice.total), places=2)

	def test_a_refund_is_on_the_page_negative_and_names_its_bill(self):
		order = self._sold(qty=2)
		line = returns.returnable(order)["items"][0]["row"]
		refund = returns.create_return(order, items=[{"row": line, "qty": 1}], reason_code=REASON)

		row = next(row for row in self._rows("invoice") if row.get("invoice") == refund["credit_note"])
		self.assertEqual(row["against"], order.sales_invoice)
		self.assertLess(row["total"], 0)

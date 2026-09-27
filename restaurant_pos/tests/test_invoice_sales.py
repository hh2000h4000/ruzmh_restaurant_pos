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
from restaurant_pos.utils import reporting, returns

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

	def test_a_bill_says_what_came_off_it_and_why(self):
		"""The bill's one discount figure, taken apart into the offer and the cashier's own."""
		discounted = self._sold()
		plain = self._sold()
		frappe.db.set_value(
			"Restaurant Order",
			discounted.name,
			{"discount_amount": 10, "promotion": "RPOS report offer", "promotion_amount": 6},
		)

		_columns, rows = report.execute(
			{"from_date": today(), "to_date": today(), "view": "invoice", "discounted_only": 1}
		)
		row = next(row for row in rows if row.get("invoice") == discounted.sales_invoice)
		self.assertAlmostEqual(row["offer_amount"], 6, places=2)
		self.assertAlmostEqual(row["manual_discount"], 4, places=2)
		self.assertNotIn(plain.sales_invoice, [row.get("invoice") for row in rows])

	def test_a_bill_is_found_under_its_own_till_and_no_other(self):
		"""`D-279` — three tills in one branch are three answers to «who sold this?»."""
		order = self._sold()
		period = {"from_date": today(), "to_date": today(), "view": "invoice"}

		_columns, mine = report.execute({**period, "pos_profile": self.profile})
		row = next(row for row in mine if row.get("invoice") == order.sales_invoice)
		self.assertEqual(row["till"], self.profile)

		_columns, other = report.execute({**period, "pos_profile": "RPOS No Such Till"})
		self.assertNotIn(order.sales_invoice, [row.get("invoice") for row in other])

	def test_every_report_that_walks_bills_is_scoped_by_till(self):
		"""The one place fourteen reports take their scope from."""
		chosen = reporting.scope(frappe._dict(branch="B", pos_profile="T", order_type="O"))

		self.assertEqual(chosen, {"branch": "B", "pos_profile": "T", "order_type": "O"})

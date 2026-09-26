# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The channels side by side (`D-273`).

A bill lands on its order type's line with the same money `Daily Sales` gives
it, a refund comes off the channel of the bill it reverses, and the shares add
up to the whole.

**Measured as differences** — the suite's own bills pile up on the test site.

Refs: FR-11.2, D-273
"""

import frappe
from frappe.utils import flt, today

from restaurant_pos.restaurant_pos.report.channel_sales import channel_sales as report
from restaurant_pos.tests.test_payment import PaymentTestBase
from restaurant_pos.utils import returns

REASON = "goods_returned"
EMPTY = {"bills": 0, "total": 0.0, "returns": 0.0, "net": 0.0}


class TestTheChannels(PaymentTestBase):
	def _rows(self) -> list[dict]:
		_columns, rows = report.execute({"from_date": today(), "to_date": today()})
		return rows

	def _line(self, order_type: str) -> dict:
		return next((row for row in self._rows() if row["order_type"] == order_type), EMPTY)

	def test_a_bill_lands_on_its_channel(self):
		order = self._payable_order(qty=1)
		before = self._line(order.order_type)
		self._pay(order)

		after = self._line(order.order_type)
		invoice = frappe.get_doc("Sales Invoice", order.sales_invoice)
		self.assertEqual(after["bills"] - before["bills"], 1)
		self.assertAlmostEqual(after["total"] - before["total"], flt(invoice.grand_total), places=2)

	def test_a_refund_comes_off_the_channel_of_its_bill(self):
		order = self._payable_order(qty=2)
		self._pay(order)
		before = self._line(order.order_type)

		line = returns.returnable(order)["items"][0]["row"]
		returns.create_return(order, items=[{"row": line, "qty": 1}], reason_code=REASON)

		after = self._line(order.order_type)
		self.assertGreater(after["returns"], before["returns"])
		self.assertLess(after["net"], before["net"])

	def test_the_shares_add_up_to_the_whole(self):
		self._pay(self._payable_order(qty=1))
		rows = self._rows()

		self.assertIsNone(rows[-1]["order_type"], "the last line is the period's")
		self.assertAlmostEqual(sum(row["share"] for row in rows[:-1]), 100, delta=0.1)

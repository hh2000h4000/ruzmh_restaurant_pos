# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The product mix: which dishes sold over a stretch of days (`D-243`).

An owner drops a dish from the menu on the strength of this report, so the
claims tested are the ones that decision rests on: a settled bill counts and an
open one does not, a refund comes off the dish it was refunded on, the money is
net of VAT whichever way the branch prices it, and the window is the window
asked for.

**Measured as differences, not totals.** The report sums the whole site, and the
suite's own bills pile up on one dish across runs — hundreds of them. An
absolute figure here would assert the state of the test database rather than the
behaviour of the report.

Refs: FR-11.2, D-217, D-243
"""

import frappe
from frappe.utils import add_days, flt, today

from restaurant_pos.restaurant_pos.report.item_sales import item_sales as report
from restaurant_pos.tests.test_order import ITEM
from restaurant_pos.tests.test_payment import PaymentTestBase
from restaurant_pos.utils import returns

REASON = "goods_returned"

EMPTY = {"qty": 0.0, "returned_qty": 0.0, "net_qty": 0.0, "amount": 0.0}


def _row(key: str = ITEM, **filters) -> dict:
	"""One line of the report, or an empty one when the dish is not on it."""
	filters = {"from_date": today(), "to_date": today(), **filters}
	_columns, rows = report.execute(filters)
	by_key = {row.get("item_code") or row["item_group"]: row for row in rows}
	return by_key.get(key) or dict(EMPTY)


def _delta(before: dict, after: dict) -> dict:
	return {
		field: flt(after[field] - before[field], 2) for field in ("qty", "returned_qty", "net_qty", "amount")
	}


class TestWhatSold(PaymentTestBase):
	def test_a_settled_bill_puts_its_dishes_on_the_report(self):
		before = _row()

		order = self._payable_order(qty=3)
		self._pay(order)

		moved = _delta(before, _row())
		self.assertEqual(moved["qty"], 3)
		self.assertEqual(moved["returned_qty"], 0)
		self.assertEqual(moved["net_qty"], 3)
		self.assertGreater(moved["amount"], 0)

	def test_a_bill_nobody_paid_sold_nothing(self):
		"""An open bill has taken no money; the day's report is where it is counted."""
		before = _row()

		self._payable_order(qty=2)

		self.assertEqual(_delta(before, _row())["qty"], 0)

	def test_the_share_of_takings_adds_up(self):
		order = self._payable_order(qty=2)
		self._pay(order)

		_columns, rows = report.execute({"from_date": today(), "to_date": today()})

		self.assertAlmostEqual(sum(row["share"] for row in rows), 100.0, places=1)

	def test_a_refund_comes_off_the_dish_it_was_refunded_on(self):
		order = self._payable_order(qty=4)
		self._pay(order)
		before = _row()

		line = returns.returnable(order)["items"][0]["row"]
		returns.create_return(order, items=[{"row": line, "qty": 1}], reason_code=REASON)

		moved = _delta(before, _row())
		self.assertEqual(moved["qty"], 0, "a refund is not a sale")
		self.assertEqual(moved["returned_qty"], 1)
		self.assertEqual(moved["net_qty"], -1)
		self.assertLess(moved["amount"], 0)

	def test_the_money_is_net_of_vat(self):
		"""`net_amount`, so the column means the same whether tax is included or added."""
		before = _row()

		order = self._payable_order(qty=1)
		self._pay(order)

		invoice = frappe.get_doc("Sales Invoice", order.sales_invoice)
		self.assertAlmostEqual(_delta(before, _row())["amount"], invoice.items[0].net_amount, places=2)


class TestTheWindowAndTheScope(PaymentTestBase):
	def test_a_bill_settled_today_is_not_in_last_week_s_figures(self):
		window = {"from_date": add_days(today(), -10), "to_date": add_days(today(), -5)}
		before = _row(**window)

		order = self._payable_order(qty=1)
		self._pay(order)

		self.assertEqual(_delta(before, _row(**window))["qty"], 0)

	def test_another_branch_s_bills_stay_out(self):
		order = self._payable_order(qty=1)
		self._pay(order)

		self.assertEqual(_row(branch="RPOS No Such Branch")["qty"], 0)

	def test_a_backwards_window_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			report.execute({"from_date": today(), "to_date": add_days(today(), -1)})

	def test_grouping_asks_the_coarser_question(self):
		group = frappe.db.get_value("Item", ITEM, "item_group")
		before = _row(group, group_by_item_group=1)

		order = self._payable_order(qty=2)
		self._pay(order)

		after = _row(group, group_by_item_group=1)
		self.assertNotIn("item_code", after)
		self.assertEqual(_delta(before, after)["qty"], 2)

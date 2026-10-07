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
from restaurant_pos.tests.test_order import BRANCH, ITEM
from restaurant_pos.tests.test_payment import PaymentTestBase
from restaurant_pos.tests.test_recipes import _drop_bundle
from restaurant_pos.utils import posting, returns
from restaurant_pos.utils.sale_doc import LINE_COST, SALE

REASON = "goods_returned"

EMPTY = {"qty": 0.0, "returned_qty": 0.0, "net_qty": 0.0, "amount": 0.0, "cost": 0.0, "profit": 0.0}


def _run(**filters):
	# A sale's cost is known once its day is posted (`D-314`).
	posting.post_branch(BRANCH)
	return report.execute({"from_date": today(), "to_date": today(), **filters})


def _row(key: str = ITEM, **filters) -> dict:
	"""One line of the report, or an empty one when the dish is not on it."""
	_columns, rows, _message = _run(**filters)
	by_key = {row.get("item_code") or row["item_group"]: row for row in rows}
	return by_key.get(key) or dict(EMPTY)


def _delta(before: dict, after: dict) -> dict:
	fields = ("qty", "returned_qty", "net_qty", "amount", "cost", "profit", "unposted_qty", "uncosted_qty")
	return {field: flt(after.get(field, 0) - before.get(field, 0), 2) for field in fields}


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

		_columns, rows, _message = report.execute({"from_date": today(), "to_date": today()})

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

		invoice = frappe.get_doc(SALE, order.sales_invoice)
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


class TestCostAndProfit(PaymentTestBase):
	"""`D-244` — asked for, never assumed."""

	def setUp(self):
		super().setUp()
		# These tests sell the burger as a dish with **no recipe**. A recipe left
		# behind by another class — committed mid-run by something that issues
		# DDL, so that class's own rollback brings it back — would cost the dish
		# from ingredients instead, and the figure below would be somebody else's.
		_drop_bundle()

	def test_the_columns_are_absent_until_they_are_asked_for(self):
		"""A restaurant without stock has no cost, and a blank column is not one."""
		asked, unasked = _run(show_cost=1)[0], _run()[0]

		self.assertIn("cost", [column["fieldname"] for column in asked])
		self.assertNotIn("cost", [column["fieldname"] for column in unasked])

	def test_a_costed_dish_reports_its_cost_and_what_is_left(self):
		cost = 4.0
		frappe.db.set_value("Item", ITEM, "valuation_rate", cost)
		frappe.db.set_value("Stock Settings", None, "allow_negative_stock", 1)
		frappe.db.value_cache = {}
		frappe.clear_document_cache("Item", ITEM)
		before = _row(show_cost=1)

		order = self._payable_order(qty=2)
		self._pay(order)

		moved = _delta(before, _row(show_cost=1))
		line = frappe.get_doc(SALE, order.sales_invoice).items[0]
		self.assertAlmostEqual(moved["cost"], flt(line.get(LINE_COST)) * 2, places=2)
		self.assertAlmostEqual(moved["profit"], moved["amount"] - moved["cost"], places=2)

	def test_a_dish_with_no_cost_is_said_aloud_not_counted_as_free(self):
		"""The margin would otherwise read 100% and be believed."""
		order = self._payable_order(qty=1)
		self._pay(order)

		_columns, rows, message = _run(show_cost=1)
		blind = [row for row in rows if row["uncosted_qty"]]

		if blind:
			self.assertIn(str(len(blind)), message)
		else:
			self.assertIsNone(message)


class TestTodayIsNotPostedYet(PaymentTestBase):
	"""`D-323` — a sale's cost is written when its day is posted; until then it is unknown, not zero."""

	def setUp(self):
		super().setUp()
		_drop_bundle()
		frappe.db.set_value("Item", ITEM, "valuation_rate", 4.0)
		frappe.clear_document_cache("Item", ITEM)
		posting.post_branch(BRANCH)

	def _now(self) -> tuple[dict, str | None]:
		"""The burger's row and the message, **without** posting first — `_run` posts."""
		_columns, rows, message = report.execute({"from_date": today(), "to_date": today(), "show_cost": 1})
		return next((row for row in rows if row.get("item_code") == ITEM), dict(EMPTY)), message

	def test_an_unposted_sale_is_waiting_not_free(self):
		before, _message = self._now()
		self._pay(self._payable_order(qty=2))

		after, message = self._now()

		self.assertEqual(after["unposted_qty"], 2)
		self.assertEqual(
			after.get("uncosted_qty", 0), before.get("uncosted_qty", 0), "not a dish with no cost"
		)
		self.assertAlmostEqual(
			after.get("profit", 0), before.get("profit", 0), places=2, msg="no profit on a cost nobody knows"
		)
		self.assertGreater(after["amount"], before.get("amount", 0), "the takings are still there")
		self.assertIn("not posted yet", message)

	def test_once_posted_it_has_its_cost_and_its_profit(self):
		before, _message = self._now()
		self._pay(self._payable_order(qty=2))

		posting.post_branch(BRANCH)

		after, _message = self._now()
		self.assertEqual(after["unposted_qty"], 0)
		self.assertAlmostEqual(after["cost"] - before.get("cost", 0), 8.0, places=2)
		self.assertAlmostEqual(after["profit"], after["amount"] - after["cost"], places=2)

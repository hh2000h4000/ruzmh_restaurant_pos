# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The three reports an owner reviews rather than sells from (`D-247`).

`Sales Exceptions` is the loss-prevention one — every discount, void and refund
with the person who gave it and the person who approved it. `Staff Sales` is who
took how much over a month rather than over one drawer. `Payment Types` is how
much of the trade was cash, which decides how often somebody walks to the bank.

**Measured as differences**, like every other period report here: the suite's own
bills pile up on the test site, so an absolute figure would assert the database
rather than the report.

Refs: FR-8.3, FR-11.2, FR-12.5, D-247
"""

import frappe
from frappe.utils import flt, today

from restaurant_pos.restaurant_pos.report.payment_types import payment_types as methods
from restaurant_pos.restaurant_pos.report.sales_exceptions import sales_exceptions as exceptions
from restaurant_pos.restaurant_pos.report.staff_sales import staff_sales as staff
from restaurant_pos.tests.test_payment import CASH, PaymentTestBase
from restaurant_pos.utils import order as orders
from restaurant_pos.utils import returns
from restaurant_pos.utils.sale_doc import SALE

REASON = "goods_returned"


def _window(**extra) -> dict:
	return {"from_date": today(), "to_date": today(), **extra}


def _exception_rows(**extra) -> list[dict]:
	_columns, rows, _message = exceptions.execute(_window(**extra))
	return rows


def _staff_row(user: str, **extra) -> dict:
	_columns, rows = staff.execute(_window(**extra))
	for row in rows:
		if row["cashier"] == user:
			return row
	return {"bills": 0, "sales": 0.0, "returns": 0.0, "net": 0.0}


def _method_row(method: str, **extra) -> dict:
	_columns, rows = methods.execute(_window(**extra))
	for row in rows:
		if row["method"] == method:
			return row
	return {"taken": 0.0, "refunded": 0.0, "net": 0.0}


class TestSalesExceptions(PaymentTestBase):
	def _sent(self, qty: int):
		"""A bill the kitchen already has — a line before that is removed, not voided."""
		order = self._payable_order(qty=qty)
		order.items[0].status = "sent"
		order.save(ignore_permissions=True)
		return order

	def test_a_void_after_the_kitchen_had_it_lands_on_the_report_with_its_reason(self):
		before = len(_exception_rows(action_type="void_item"))

		order = self._sent(qty=2)
		orders.void_item(order, item_idx=1, reason="tasted wrong")

		rows = _exception_rows(action_type="void_item")
		self.assertEqual(len(rows) - before, 1)
		self.assertEqual(rows[0]["reason"], "tasted wrong")
		self.assertEqual(rows[0]["cashier"], frappe.session.user)

	def test_the_amount_is_read_by_the_key_its_own_action_uses(self):
		"""A void keeps it under `amount`, a refund under `refund_amount`."""
		order = self._payable_order(qty=1)
		self._pay(order)
		line = returns.returnable(order)["items"][0]["row"]
		returns.create_return(order, items=[{"row": line, "qty": 1}], reason_code=REASON)

		refunds = _exception_rows(action_type="return_created")

		self.assertTrue(refunds)
		self.assertGreater(flt(refunds[0]["amount"]), 0, "the refund figure did not come through")

	def test_grouping_asks_who_rather_than_what(self):
		order = self._sent(qty=1)
		orders.void_item(order, item_idx=1, reason="dropped it")

		rows = _exception_rows(group_by_staff=1)
		mine = [row for row in rows if row["cashier"] == frappe.session.user]

		self.assertTrue(mine)
		self.assertGreaterEqual(mine[0]["count"], 1)
		self.assertIn("count", mine[0])

	def test_an_offer_the_restaurant_published_is_not_an_exception(self):
		"""A promotion is the menu; a discount typed by hand is the exception."""
		self.assertNotIn("promotion_applied", exceptions.AMOUNT_KEYS)

	def test_another_branch_s_acts_stay_out(self):
		order = self._sent(qty=1)
		orders.void_item(order, item_idx=1, reason="dropped it")

		self.assertEqual(_exception_rows(branch="RPOS No Such Branch"), [])


class TestStaffSales(PaymentTestBase):
	def test_a_settled_bill_lands_on_whoever_took_the_money(self):
		me = frappe.session.user
		before = _staff_row(me)

		order = self._payable_order(qty=2)
		self._pay(order)

		after = _staff_row(me)
		self.assertEqual(after["bills"] - before["bills"], 1)
		self.assertGreater(after["sales"], before["sales"])

	def test_a_refund_comes_off_the_person_who_paid_it_out(self):
		order = self._payable_order(qty=2)
		self._pay(order)
		before = _staff_row(frappe.session.user)

		line = returns.returnable(order)["items"][0]["row"]
		returns.create_return(order, items=[{"row": line, "qty": 1}], reason_code=REASON)

		after = _staff_row(frappe.session.user)
		self.assertGreater(after["returns"], before["returns"])
		self.assertLess(after["net"] - before["net"], after["sales"] - before["sales"])

	def test_the_last_line_averages_the_period_and_does_not_add_up_averages(self):
		order = self._payable_order(qty=1)
		self._pay(order)

		_columns, rows = staff.execute(_window())
		total = rows[-1]

		self.assertIsNone(total["cashier"], "the last line is the period's, not a person's")
		self.assertAlmostEqual(total["average"], total["sales"] / total["bills"], places=2)


class TestPaymentTypes(PaymentTestBase):
	def test_what_was_taken_in_cash_shows_under_cash(self):
		before = _method_row(CASH)

		order = self._payable_order(qty=1)
		self._pay(order)

		paid = flt(frappe.db.get_value(SALE, order.sales_invoice, "grand_total"))
		self.assertAlmostEqual(_method_row(CASH)["taken"] - before["taken"], paid, places=2)

	def test_a_refund_is_listed_apart_from_the_takings(self):
		"""The net alone cannot tell a quiet day from a busy one with a refund in it."""
		order = self._payable_order(qty=2)
		self._pay(order)
		before = _method_row(CASH)

		line = returns.returnable(order)["items"][0]["row"]
		returns.create_return(order, items=[{"row": line, "qty": 1}], reason_code=REASON)

		after = _method_row(CASH)
		self.assertGreater(after["refunded"], before["refunded"])
		self.assertLess(after["net"] - before["net"], after["taken"] - before["taken"])

	def test_credit_is_named_as_credit(self):
		"""`D-029` — money a platform owes was never in the drawer."""
		_columns, rows = methods.execute(_window())

		for row in rows[:-1]:
			with self.subTest(method=row["method"]):
				self.assertIn(row["kind"], ("till", "credit"))

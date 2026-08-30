# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Returns and refunds.

A return is the only way to reverse a sale (`BR-050a`, `D-063`), which makes
these the tests that stand between a customer and being refunded twice, or not
at all.

Refs: FR-9.1..FR-9.3, BR-050..BR-055, D-064
"""

import frappe

from restaurant_pos.tests.test_order import ITEM, OrderTestBase
from restaurant_pos.tests.test_payment import CASH, _ensure_fiscal_year
from restaurant_pos.utils import order as orders
from restaurant_pos.utils import payment
from restaurant_pos.utils import returns as service
from restaurant_pos.utils import shift as shift_service

REASON = "goods_returned"


class ReturnTestBase(OrderTestBase):
	def _paid(self, qty: float = 2):
		_ensure_fiscal_year()

		order = self._order()
		orders.add_item(order, item=ITEM, qty=qty)
		order.reload()
		payment.process_payment(order, payments=[{"method": CASH, "amount": order.total_amount}])
		order.reload()
		return order

	def _row(self, order) -> str:
		return service.returnable(order)["items"][0]["row"]


class TestWhatCanComeBack(ReturnTestBase):
	def test_an_unpaid_order_has_nothing_to_return(self):
		"""BR-050."""
		with self.assertRaises(frappe.ValidationError):
			service.returnable(self._order())

	def test_a_paid_order_offers_its_lines(self):
		order = self._paid()
		summary = service.returnable(order)

		self.assertEqual(len(summary["items"]), 1)
		self.assertEqual(summary["items"][0]["returnable"], 2)
		self.assertEqual(summary["items"][0]["returned"], 0)
		self.assertFalse(summary["fully_returned"])
		self.assertEqual(summary["paid_with"][0]["method"], CASH)


class TestReturningPartOfABill(ReturnTestBase):
	def test_a_partial_return_leaves_the_rest(self):
		"""BR-051, FR-9.3 — and the second attempt must see the first."""
		order = self._paid(qty=3)

		service.create_return(order, items=[{"row": self._row(order), "qty": 1}], reason_code=REASON)

		summary = service.returnable(order)
		self.assertEqual(summary["items"][0]["returned"], 1)
		self.assertEqual(summary["items"][0]["returnable"], 2)
		self.assertFalse(summary["fully_returned"])

	def test_returning_everything_closes_the_door(self):
		order = self._paid(qty=2)

		service.create_return(order, items=[{"row": self._row(order), "qty": 2}], reason_code=REASON)

		summary = service.returnable(order)
		self.assertTrue(summary["fully_returned"])
		self.assertEqual(summary["items"][0]["returnable"], 0)

	def test_more_than_was_sold_is_refused(self):
		"""FR-9.3."""
		order = self._paid(qty=2)

		with self.assertRaises(frappe.ValidationError):
			service.create_return(order, items=[{"row": self._row(order), "qty": 3}], reason_code=REASON)

	def test_a_second_return_cannot_exceed_what_is_left(self):
		order = self._paid(qty=2)
		row = self._row(order)
		service.create_return(order, items=[{"row": row, "qty": 1}], reason_code=REASON)

		with self.assertRaises(frappe.ValidationError):
			service.create_return(order, items=[{"row": row, "qty": 2}], reason_code=REASON)

	def test_nothing_selected_is_refused(self):
		order = self._paid()

		with self.assertRaises(frappe.ValidationError):
			service.create_return(order, items=[], reason_code=REASON)

	def test_a_reason_is_required(self):
		"""BR-052, and KSA-10 behind it (D-065).

		The code has to be one of the recognised triggers, not a sentence: a
		credit note that reaches ZATCA with free text where a trigger belongs is
		one that does not clear.
		"""
		order = self._paid()

		for bad in ("", "   ", "the customer sent it back"):
			with self.assertRaises(frappe.ValidationError):
				service.create_return(order, items=[{"row": self._row(order), "qty": 1}], reason_code=bad)

	def test_the_reason_travels_on_the_credit_note(self):
		"""D-065 — a ZATCA integration reads it from the document, not our log."""
		order = self._paid()

		result = service.create_return(
			order,
			items=[{"row": self._row(order), "qty": 1}],
			reason_code="quality_complaint",
			note="cold when it arrived",
		)

		remarks = frappe.db.get_value("Sales Invoice", result["credit_note"], "remarks")
		self.assertIn("quality_complaint", remarks)
		self.assertIn("goods return", remarks)
		self.assertIn("cold when it arrived", remarks)


class TestTheCreditNote(ReturnTestBase):
	def test_it_is_a_credit_note_against_the_original(self):
		"""BR-053 — ERPNext's own document, so the ledger and stock follow."""
		order = self._paid(qty=2)

		result = service.create_return(order, items=[{"row": self._row(order), "qty": 1}], reason_code=REASON)

		note = frappe.get_doc("Sales Invoice", result["credit_note"])
		self.assertEqual(note.docstatus, 1)
		self.assertEqual(note.is_return, 1)
		self.assertEqual(note.return_against, order.sales_invoice)
		self.assertEqual(note.items[0].qty, -1)
		self.assertLess(note.grand_total, 0)

	def test_the_refund_goes_back_the_way_it_came(self):
		"""BR-054."""
		order = self._paid(qty=1)

		result = service.create_return(order, items=[{"row": self._row(order), "qty": 1}], reason_code=REASON)

		note = frappe.get_doc("Sales Invoice", result["credit_note"])
		self.assertEqual(note.payments[0].mode_of_payment, CASH)
		self.assertLess(note.payments[0].amount, 0)
		self.assertGreater(result["refund_amount"], 0)

	def test_the_original_invoice_still_stands(self):
		"""D-063 — a return reverses a sale; it does not erase it."""
		order = self._paid(qty=2)
		service.create_return(order, items=[{"row": self._row(order), "qty": 2}], reason_code=REASON)

		self.assertEqual(frappe.db.get_value("Sales Invoice", order.sales_invoice, "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Restaurant Order", order.name, "status"), "closed")


class TestTheDrawerFollows(ReturnTestBase):
	def test_a_refund_leaves_the_expected_till(self):
		"""D-064 — cash handed back is cash the drawer must stop expecting."""
		order = self._paid(qty=2)
		entry = shift_service.selling_till(self.profile).name

		before = shift_service.summarise_till(entry)["till_expected"]
		service.create_return(order, items=[{"row": self._row(order), "qty": 1}], reason_code=REASON)
		after = shift_service.summarise_till(entry)

		self.assertLess(after["till_expected"], before)
		self.assertGreater(after["returns"], 0)

	def test_takings_are_not_quietly_netted(self):
		"""FR-8.3 — a shift that sold 100 and refunded 40 is not one that sold 60."""
		order = self._paid(qty=2)
		entry = shift_service.selling_till(self.profile).name

		sales = shift_service.summarise_till(entry)["sales"]
		service.create_return(order, items=[{"row": self._row(order), "qty": 1}], reason_code=REASON)

		self.assertEqual(shift_service.summarise_till(entry)["sales"], sales)


class TestTheShiftGate(ReturnTestBase):
	def test_no_refund_out_of_a_closed_drawer(self):
		"""BR-044, D-055 — a refund obeys the same rule as a sale."""
		order = self._paid()
		row = self._row(order)

		till = shift_service.selling_till(self.profile)
		frappe.db.set_value("POS Opening Entry", till.name, "status", "Closed")
		try:
			with self.assertRaises(frappe.ValidationError):
				service.create_return(order, items=[{"row": row, "qty": 1}], reason_code=REASON)
		finally:
			frappe.db.set_value("POS Opening Entry", till.name, "status", "Open")

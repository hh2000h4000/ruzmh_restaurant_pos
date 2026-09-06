# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Returns and refunds.

A return is the only way to reverse a sale (`BR-050a`, `D-063`), which makes
these the tests that stand between a customer and being refunded twice, or not
at all.

Refs: FR-9.1..FR-9.3, BR-050..BR-055, D-064
"""

from unittest.mock import patch

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
		# D-066 — every method the till has, so the cashier can choose.
		self.assertIn(CASH, summary["methods"])


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

	def test_a_method_the_terminal_does_not_have_is_refused(self):
		"""D-066 — the cashier chooses freely, from what the till actually has."""
		order = self._paid()

		with self.assertRaises(frappe.ValidationError):
			service.create_return(
				order,
				items=[{"row": self._row(order), "qty": 1}],
				reason_code=REASON,
				refund_method="Camel",
			)

	def test_no_window_bars_an_old_bill(self):
		"""D-066 — returns are allowed at any time, on any date.

		Nothing measures the age of a bill, so this asserts the absence of a rule:
		a sale backdated a year is still returnable today.
		"""
		order = self._paid()
		frappe.db.set_value("Sales Invoice", order.sales_invoice, "posting_date", "2025-01-01")

		result = service.create_return(order, items=[{"row": self._row(order), "qty": 1}], reason_code=REASON)
		self.assertTrue(result["credit_note"])

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


class TestTheTillCanSeeIt(ReturnTestBase):
	"""D-070 — a refund the cashier cannot find is a refund they will make twice.

	A credit note is not a `Restaurant Order`, so no list of orders could ever
	show it. What the cashier is looking for is which *bill* was refunded, and
	that is an order.
	"""

	def test_a_refunded_bill_carries_what_went_back(self):
		from restaurant_pos.api import order as order_api

		order = self._paid(qty=2)
		service.create_return(order, items=[{"row": self._row(order), "qty": 1}], reason_code=REASON)

		closed = order_api.list_orders(self.profile, view="closed")
		row = next(entry for entry in closed if entry["name"] == order.name)
		self.assertGreater(row["returned_amount"], 0)

	def test_the_returned_view_shows_only_refunded_bills(self):
		from restaurant_pos.api import order as order_api

		kept = self._paid()
		refunded = self._paid(qty=2)
		service.create_return(refunded, items=[{"row": self._row(refunded), "qty": 1}], reason_code=REASON)

		names = [row["name"] for row in order_api.list_orders(self.profile, view="returned")]
		self.assertIn(refunded.name, names)
		self.assertNotIn(kept.name, names)


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


class TestAReturnIsADocumentOfItsOwn(ReturnTestBase):
	"""A refund is an invoice in reverse, and the till has to be able to say so.

	Two things were missing and both were invisible from the code (`D-143`):
	the credit note carried no short number, so a cashier could only name it as
	`ACC-SINV-2026-00042`; and nothing printed at all, so money went back across
	the counter with no paper — while the receipt template had known how to draw
	`إشعار دائن` since it was written.
	"""

	def test_each_return_takes_the_next_number_in_the_day(self):
		"""The user's own model: sale 20, part of it back is 21, the rest is 22."""
		order = self._paid(qty=2)
		row = self._row(order)

		first = service.create_return(order, items=[{"row": row, "qty": 1}], reason_code=REASON)
		second = service.create_return(order, items=[{"row": row, "qty": 1}], reason_code=REASON)

		numbers = [first["daily_number"], second["daily_number"]]

		self.assertTrue(all(numbers), "a credit note with no number cannot be read out at a till")
		self.assertEqual(numbers[1], numbers[0] + 1, "two returns are two documents, not one")
		self.assertGreater(numbers[0], order.daily_number, "the return comes after the sale it reverses")

	def test_the_number_is_on_the_credit_note_itself(self):
		"""Not only in the reply: the list reads it off the document."""
		order = self._paid()
		result = service.create_return(order, items=[{"row": self._row(order), "qty": 1}], reason_code=REASON)

		self.assertEqual(
			frappe.db.get_value("Sales Invoice", result["credit_note"], "rpos_daily_number"),
			result["daily_number"],
		)

	def test_the_customer_leaves_with_the_paper(self):
		"""A sale prints from `process_payment`; a refund printed nothing.

		Asserted on the **request**, not on a `POS Print Job`: the job is made by
		a worker running after commit, so a test looking for one would be
		checking the queue rather than this module — and would pass or fail for
		reasons that have nothing to do with returns.
		"""
		order = self._paid()

		with patch("restaurant_pos.utils.returns.printing.enqueue_print") as queued:
			result = service.create_return(
				order, items=[{"row": self._row(order), "qty": 1}], reason_code=REASON
			)

		queued.assert_called_once_with(
			"print_receipt", invoice_name=result["credit_note"], order_name=order.name
		)


class TestTheReturnsTabListsTheReturns(ReturnTestBase):
	"""What the user reported twice: a refund the till shows as a note (`D-143`).

	The tab listed the **bills** money had gone back out of, with the refunds
	summed into one figure per bill. So a bill refunded twice looked like one
	event, and there was no row belonging to a particular credit note — nothing
	to reprint from, and nothing to check a drawer against.
	"""

	def _returns(self):
		from restaurant_pos.api.order import list_orders

		return list_orders(self.profile, view="returned")

	def test_two_refunds_on_one_bill_are_two_rows(self):
		order = self._paid(qty=2)
		row = self._row(order)
		service.create_return(order, items=[{"row": row, "qty": 1}], reason_code=REASON)
		service.create_return(order, items=[{"row": row, "qty": 1}], reason_code=REASON)

		mine = [entry for entry in self._returns() if entry["name"] == order.name]

		self.assertEqual(len(mine), 2, "one row per credit note, not one per bill")
		self.assertEqual(len({entry["credit_note"] for entry in mine}), 2)
		self.assertEqual(len({entry["daily_number"] for entry in mine}), 2)

	def test_the_amount_is_negative_because_that_is_the_direction(self):
		order = self._paid()
		service.create_return(order, items=[{"row": self._row(order), "qty": 1}], reason_code=REASON)

		mine = next(entry for entry in self._returns() if entry["name"] == order.name)

		self.assertLess(mine["total_amount"], 0)
		self.assertEqual(mine["is_return"], 1)

	def test_a_row_names_the_bill_it_reverses(self):
		order = self._paid()
		service.create_return(order, items=[{"row": self._row(order), "qty": 1}], reason_code=REASON)

		mine = next(entry for entry in self._returns() if entry["name"] == order.name)

		self.assertEqual(mine["returns_daily_number"], order.daily_number)
		self.assertNotEqual(mine["daily_number"], order.daily_number)

	def test_a_bill_with_nothing_returned_is_not_in_the_tab(self):
		order = self._paid()

		self.assertNotIn(order.name, [entry["name"] for entry in self._returns()])


class TestTheScreenIsToldBeforeTheButton(ReturnTestBase):
	"""`BR-055` and `D-147` — the rule the till could not answer.

	A refund out of a shift that has already been counted takes a manager's PIN
	even from someone holding `can_create_return`. That rule is right; what was
	wrong is that it was **only** reachable by pressing the button: the server
	said "manager authorisation is required" and the return screen had no PIN
	box, so the cashier was at a dead end with a customer waiting.

	`returnable()` now answers it up front, from the same helper that enforces
	it — one function, two callers (`CLAUDE.md` §5.5), so the screen cannot come
	to a different conclusion from the endpoint.
	"""

	def test_a_bill_from_this_shift_needs_nobody(self):
		order = self._paid()

		self.assertFalse(service.returnable(order)["needs_manager"])

	def test_a_bill_from_a_counted_shift_says_so(self):
		order = self._paid()
		frappe.db.set_value("Restaurant Order", order.name, "restaurant_shift", "SHF-SOMEBODY-ELSES")
		order.reload()

		self.assertTrue(service.returnable(order)["needs_manager"])

	def test_and_the_refusal_agrees_with_it(self):
		"""The screen's warning and the server's refusal are the same fact."""
		order = self._paid()
		frappe.db.set_value("Restaurant Order", order.name, "restaurant_shift", "SHF-SOMEBODY-ELSES")
		order.reload()

		with self.assertRaises(frappe.PermissionError):
			service.create_return(order, items=[{"row": self._row(order), "qty": 1}], reason_code=REASON)

	def test_a_manager_token_opens_it(self):
		"""And the door the screen now offers actually leads somewhere."""
		from restaurant_pos.utils import permissions as perms

		order = self._paid()
		frappe.db.set_value("Restaurant Order", order.name, "restaurant_shift", "SHF-SOMEBODY-ELSES")
		order.reload()

		token = perms.issue_override_token("can_create_return", frappe.session.user)
		result = service.create_return(
			order,
			items=[{"row": self._row(order), "qty": 1}],
			reason_code=REASON,
			override_token=token,
		)

		self.assertTrue(result["credit_note"])


class TestARealCashierCanRefund(ReturnTestBase):
	"""The test that was missing, and the defect it was hiding (`D-144`).

	Every test above runs as Administrator, who is allowed everything by the
	first line of `frappe.has_permission`. Under a real login the refund never
	got as far as our own rules: ERPNext's mapper asked the session for rights
	on `Sales Invoice`, no POS role has any, and the cashier got a bare
	`PermissionError` — an empty screen for a customer standing at the counter
	with their money in the till.

	So the assertion is not about the amount. It is that the whole path runs
	**as a cashier**: preview, refund, and the number it comes back with.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from restaurant_pos.tests.test_permissions import SENIOR, _make_user

		# A senior holds `can_create_return` outright, which is the shortest
		# real login that reaches the mapper — a plain cashier needs a manager's
		# PIN first, and that is a different rule, tested elsewhere.
		cls.senior = _make_user(SENIOR, "POS Senior Cashier")

	def setUp(self):
		super().setUp()
		self.order = self._paid(qty=2)
		self.row = self._row(self.order)
		frappe.set_user(self.senior)
		frappe.local.rpos_permission_cache = {}

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.rpos_permission_cache = {}
		super().tearDown()

	def test_a_cashier_can_price_a_return_before_committing_to_it(self):
		quoted = service.preview(self.order, items=[{"row": self.row, "qty": 1}])

		self.assertGreater(quoted["refund_amount"], 0)

	def test_a_cashier_can_actually_refund(self):
		result = service.create_return(self.order, items=[{"row": self.row, "qty": 1}], reason_code=REASON)

		self.assertTrue(result["credit_note"])
		self.assertGreater(result["daily_number"], self.order.daily_number)

	def test_the_credit_note_carries_the_cashier_name_not_the_frameworks(self):
		"""The rights are borrowed for the mapping only, never for the document."""
		result = service.create_return(self.order, items=[{"row": self.row, "qty": 1}], reason_code=REASON)

		self.assertEqual(frappe.db.get_value("Sales Invoice", result["credit_note"], "owner"), self.senior)

	def test_the_session_is_handed_back(self):
		service.create_return(self.order, items=[{"row": self.row, "qty": 1}], reason_code=REASON)

		self.assertEqual(frappe.session.user, self.senior)

	def test_the_session_is_handed_back_even_when_the_mapping_fails(self):
		"""Borrowed rights are given back on the way out of a failure too.

		A cashier left holding Administrator's session because ERPNext raised
		mid-map would be a far worse defect than the one being fixed.
		"""
		with patch(
			"erpnext.controllers.sales_and_purchase_return.make_return_doc",
			side_effect=frappe.ValidationError("no"),
		):
			with self.assertRaises(frappe.ValidationError):
				service.create_return(self.order, items=[{"row": self.row, "qty": 1}], reason_code=REASON)

		self.assertEqual(frappe.session.user, self.senior)

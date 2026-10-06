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
from frappe.utils import add_to_date, flt, get_datetime

from restaurant_pos.api import returns as api_returns
from restaurant_pos.tests.test_order import ITEM, OrderTestBase
from restaurant_pos.tests.test_payment import CASH, _ensure_fiscal_year
from restaurant_pos.utils import order as orders
from restaurant_pos.utils import payment, totals
from restaurant_pos.utils import returns as service
from restaurant_pos.utils import shift as shift_service
from restaurant_pos.utils.sale_doc import SALE

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

		remarks = frappe.db.get_value(SALE, result["credit_note"], "remarks")
		self.assertIn("quality_complaint", remarks)
		self.assertIn("goods return", remarks)
		self.assertIn("cold when it arrived", remarks)


class TestTheCreditNote(ReturnTestBase):
	def test_it_is_a_credit_note_against_the_original(self):
		"""BR-053 — ERPNext's own document, so the ledger and stock follow."""
		order = self._paid(qty=2)

		result = service.create_return(order, items=[{"row": self._row(order), "qty": 1}], reason_code=REASON)

		note = frappe.get_doc(SALE, result["credit_note"])
		self.assertEqual(note.docstatus, 1)
		self.assertEqual(note.is_return, 1)
		self.assertEqual(note.return_against, order.sales_invoice)
		self.assertEqual(note.items[0].qty, -1)
		self.assertLess(note.grand_total, 0)

	def test_the_refund_goes_back_the_way_it_came(self):
		"""BR-054."""
		order = self._paid(qty=1)

		result = service.create_return(order, items=[{"row": self._row(order), "qty": 1}], reason_code=REASON)

		note = frappe.get_doc(SALE, result["credit_note"])
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
		frappe.db.set_value(SALE, order.sales_invoice, "posting_date", "2025-01-01")

		result = service.create_return(order, items=[{"row": self._row(order), "qty": 1}], reason_code=REASON)
		self.assertTrue(result["credit_note"])

	def test_a_clock_that_stepped_back_does_not_refuse_the_refund(self):
		"""`D-261` — a refund in the second after a step back is not dated before its sale.

		ERPNext refuses a return dated earlier than its invoice. The gate lost a
		run to exactly this: the clock stepped back between the sale and the refund.
		"""
		order = self._paid()
		sold = frappe.db.get_value(SALE, order.sales_invoice, ["posting_date", "posting_time"])
		sold_at = get_datetime(f"{sold[0]} {sold[1]}")

		with patch(
			"restaurant_pos.utils.returns.now_datetime", return_value=add_to_date(sold_at, seconds=-2)
		):
			result = service.create_return(
				order, items=[{"row": self._row(order), "qty": 1}], reason_code=REASON
			)

		note = frappe.db.get_value(SALE, result["credit_note"], ["posting_date", "posting_time"])
		self.assertEqual(get_datetime(f"{note[0]} {note[1]}"), sold_at)

	def test_the_original_invoice_still_stands(self):
		"""D-063 — a return reverses a sale; it does not erase it."""
		order = self._paid(qty=2)
		service.create_return(order, items=[{"row": self._row(order), "qty": 2}], reason_code=REASON)

		self.assertEqual(frappe.db.get_value(SALE, order.sales_invoice, "docstatus"), 1)
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


#: Before any till was opened — outside every period a test can be in.
LONG_AGO = "2000-01-01 12:00:00"

#: A business day that is not the one open now.
OLDER_DAY = "RPOS-TEST-OLDER-DAY"


class TestMoneyCountsWhereItMoved(ReturnTestBase):
	"""`D-217` — a bill and a refund count in the period they happened in.

	The user's rule: *the day a bill is closed is the day that counts for the
	money.* The day's report and the drawer both chose orders by the day that
	**opened** them, so a bill carried from an earlier day and paid now was in
	no report and no drawer, and a refund on an older sale went into the older
	day's report — already closed — while the cash left today's drawer.
	"""

	def _day(self) -> str:
		return frappe.db.get_value("POS Profile", self.profile, "restaurant_shift")

	def _move(self, order, **fields) -> None:
		frappe.db.set_value("Restaurant Order", order.name, fields, update_modified=False)

	def test_a_bill_from_an_earlier_day_paid_now_counts_in_todays_report(self):
		order = self._paid()
		before = shift_service.summarise(self._day())["sales"]

		self._move(order, restaurant_shift=OLDER_DAY)

		self.assertEqual(shift_service.summarise(self._day())["sales"], before)

	def test_and_in_the_drawer_that_took_the_money(self):
		order = self._paid()
		entry = shift_service.selling_till(self.profile).name
		before = shift_service.summarise_till(entry)["till_expected"]

		self._move(order, restaurant_shift=OLDER_DAY)

		self.assertEqual(shift_service.summarise_till(entry)["till_expected"], before)

	def _refund_older_sale(self, report):
		"""Refund a sale, then move the sale out of today — as if it were last week's.

		Returns the sale's amount, the refund's, and the report read after the sale
		and before the refund — so each test measures the refund itself, rather
		than two totals that would agree if it counted nowhere.
		"""
		order = self._paid(qty=2)
		before = report()
		refund = service.create_return(order, items=[{"row": self._row(order), "qty": 1}], reason_code=REASON)
		self._move(order, restaurant_shift=OLDER_DAY, closed_at=LONG_AGO)
		return flt(order.total_amount), refund["refund_amount"], before, report()

	def test_a_refund_today_on_an_older_sale_is_in_todays_returns(self):
		sale, refund, before, after = self._refund_older_sale(lambda: shift_service.summarise(self._day()))

		self.assertAlmostEqual(after["returns"] - before["returns"], refund, places=2)
		# The sale left today; the refund stayed.
		self.assertAlmostEqual(before["sales"] - after["sales"], sale, places=2)

	def test_and_it_leaves_the_drawer_it_was_paid_out_of(self):
		entry = shift_service.selling_till(self.profile).name
		sale, refund, before, after = self._refund_older_sale(lambda: shift_service.summarise_till(entry))

		self.assertAlmostEqual(after["returns"] - before["returns"], refund, places=2)
		# The sale's cash left with the sale, and the refund's cash left the drawer.
		self.assertAlmostEqual(before["till_expected"] - after["till_expected"], sale + refund, places=2)


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
			frappe.db.get_value(SALE, result["credit_note"], "rpos_daily_number"),
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

		self.assertEqual(frappe.db.get_value(SALE, result["credit_note"], "owner"), self.senior)

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


class TheRefundRowOpensTheRefund(ReturnTestBase):
	"""`D-171` — the row carried the sale's name, so it opened the sale.

	A cashier who returned two dishes off a bill of four tapped the refund row
	and got all four, at positive prices, on a row labelled *refund* showing a
	negative figure. The two that came back were nowhere on the screen.

	**The credit note was never wrong.** It holds exactly the returned rows at
	negative quantities, and printing it prints those. Only the screen was
	reading the other document — which is why this reads the credit note rather
	than rebuilding anything.
	"""

	def _refunded(self, of: float = 1):
		"""A paid bill of two, with `of` sent back."""
		order = self._paid(qty=2)
		credit = service.create_return(
			order,
			items=[{"row": self._row(order), "qty": of}],
			reason_code=REASON,
			refund_method=CASH,
		)
		order.reload()
		return order, credit["credit_note"]

	def test_it_holds_only_what_came_back(self):
		_, credit = self._refunded(of=1)

		detail = api_returns.get_refund(credit)

		self.assertEqual(len(detail["items"]), 1, "one line back, not the whole bill")
		self.assertEqual(detail["items"][0]["qty"], -1.0, "negative: goods went back")

	def test_every_figure_on_it_is_negative(self):
		"""So a printed refund reads as money leaving, not arriving."""
		_, credit = self._refunded()

		detail = api_returns.get_refund(credit)

		self.assertLess(detail["total_amount"], 0)
		self.assertLessEqual(detail["tax_amount"], 0)
		self.assertTrue(all(line["amount"] < 0 for line in detail["items"]))

	def test_it_names_the_bill_it_reverses(self):
		"""Both numbers, because a refund has its own (`D-143`) and a cashier
		holding the paper needs to find the sale it came off."""
		order, credit = self._refunded()

		detail = api_returns.get_refund(credit)

		self.assertEqual(detail["returns_daily_number"], order.daily_number)
		self.assertNotEqual(detail["daily_number"], order.daily_number)

	def test_a_sale_is_not_a_refund(self):
		"""Asked for the wrong document, it says so rather than answering."""
		order = self._paid()

		with self.assertRaises(frappe.ValidationError):
			api_returns.get_refund(order.sales_invoice)

	def test_it_names_the_bill_so_branch_access_has_something_to_check(self):
		"""A credit note carries no branch of its own.

		Its authority is the sale it reverses, so the detail has to name that
		order — `validate_branch_access` reads the branch off it, and without the
		link there is nothing to check against.
		"""
		order, credit = self._refunded()

		self.assertEqual(api_returns.get_refund(credit)["order_name"], order.name)


class TestADiscountedBillComesBackInShares(ReturnTestBase):
	"""D-190 — a partial return takes back its share of the discount, not all of it.

	ERPNext's `make_return_doc` copies the sale's whole `discount_amount` onto the
	credit note, and a partial return trims the lines and keeps it. So one dish
	back off a discounted bill of two carried the **entire** discount, and the
	customer was refunded the dish minus the whole bill's reduction.

	Found building loyalty, because a redemption is a discount (`D-189`) — but
	every cashier's discount and every offer has been refunded this way.
	"""

	def _discounted(self):
		_ensure_fiscal_year()

		order = self._order()
		orders.add_item(order, item=ITEM, qty=2)
		order.reload()

		# Set on the bill and priced, the way a discount chosen earlier arrives at
		# the payment — so no ceiling is asked, which is not what is tested here.
		order.discount_type = "amount"
		order.discount_value = 10
		totals.calculate(order)
		order.save(ignore_permissions=True)

		payment.process_payment(order, payments=[{"method": CASH, "amount": order.total_amount}])
		order.reload()
		return order

	def _paid_for(self, order) -> float:
		invoice = frappe.db.get_value(
			SALE, order.sales_invoice, ["rounded_total", "grand_total"], as_dict=True
		)
		return flt(invoice.rounded_total or invoice.grand_total)

	def test_half_the_bill_back_is_half_the_money_paid(self):
		order = self._discounted()
		paid = self._paid_for(order)

		result = service.create_return(order, items=[{"row": self._row(order), "qty": 1}], reason_code=REASON)

		self.assertAlmostEqual(result["refund_amount"], paid / 2, delta=0.05)

	def test_the_whole_bill_back_in_two_parts_is_every_riyal_paid(self):
		order = self._discounted()
		paid = self._paid_for(order)
		row = self._row(order)

		first = service.create_return(order, items=[{"row": row, "qty": 1}], reason_code=REASON)
		second = service.create_return(order, items=[{"row": row, "qty": 1}], reason_code=REASON)

		self.assertAlmostEqual(first["refund_amount"] + second["refund_amount"], paid, places=2)

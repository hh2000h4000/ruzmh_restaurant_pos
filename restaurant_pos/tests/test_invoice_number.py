# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Invoice numbers are the branch, the terminal, then a count (`D-309`).

    1002-01-000001

One counter for the company made every till wait for the one before it; one per
terminal does not, and it is how ZATCA counts. So this pins the three things the
number has to be: **told apart** (no two terminals can share one), **unbroken**
(it cannot change under invoices already numbered), and **there before the first
sale** (the counter row is not made inside a customer's payment).
"""

import uuid

import frappe
from frappe.model.naming import NamingSeries
from frappe.tests.utils import FrappeTestCase

from restaurant_pos.tests.test_returns import REASON, ReturnTestBase
from restaurant_pos.utils import invoice_number as numbers
from restaurant_pos.utils import quick_setup
from restaurant_pos.utils import returns as returns_service
from restaurant_pos.utils.order import branch_of_profile


def _branch_with_a_till(**over) -> dict:
	tag = uuid.uuid4().hex[:6]
	return quick_setup.run(
		{
			"company": frappe.db.get_value("Company", {}, "name"),
			"branch": f"RPOS Numbered {tag}",
			"takeaway": 1,
			"terminal": f"RPOS Numbered Till {tag}",
			**over,
		}
	)


def _second_till(first: str) -> "frappe.model.document.Document":
	"""Another terminal in the same branch as ``first`` — copied as the desk's Duplicate copies.

	`ignore_no_copy=False` is what makes it the desk's copy (`D-393`): the
	Duplicate button (`frappe.model.copy_doc` in `create_new.js`) skips every
	`no_copy` field, and `frappe.copy_doc` does the same only when told to — by
	default it copies them all. `rpos_branch` is one, so a twin takes its branch
	from its hall again, and a twin with no hall has none, as before.
	"""
	twin = frappe.copy_doc(frappe.get_doc("POS Profile", first), ignore_no_copy=False)
	twin.name = None
	twin.set("__newname", f"RPOS Numbered Twin {uuid.uuid4().hex[:6]}")
	twin.set(numbers.DEVICE_NUMBER, None)
	return twin


class ABranchAndItsTerminalsAreNumbered(FrappeTestCase):
	def test_a_new_branch_and_its_terminal_are_given_numbers(self):
		made = _branch_with_a_till()

		branch_number = frappe.db.get_value("Branch", made["branch"], numbers.BRANCH_NUMBER)
		device_number = frappe.db.get_value("POS Profile", made["pos_profile"], numbers.DEVICE_NUMBER)

		self.assertGreaterEqual(int(branch_number), numbers.FIRST_BRANCH)
		self.assertEqual(device_number, "01", "the first terminal of a branch")
		self.assertEqual(numbers.series_for(made["pos_profile"]), f"{branch_number}-01-.######")

	def test_two_branches_never_share_a_number(self):
		first = frappe.db.get_value("Branch", _branch_with_a_till()["branch"], numbers.BRANCH_NUMBER)
		second = frappe.db.get_value("Branch", _branch_with_a_till()["branch"], numbers.BRANCH_NUMBER)

		self.assertNotEqual(first, second)

	def test_the_second_terminal_of_a_branch_is_02(self):
		made = _branch_with_a_till()

		twin = _second_till(made["pos_profile"]).insert()

		self.assertEqual(twin.get(numbers.DEVICE_NUMBER), "02")
		self.assertNotEqual(numbers.series_for(twin.name), numbers.series_for(made["pos_profile"]))

	def test_a_number_somebody_chose_is_kept_as_they_meant_it(self):
		"""Fatek's scheme: the branch's own number at the front."""
		made = _branch_with_a_till()
		branch = frappe.get_doc("Branch", made["branch"])
		chosen = str(900000 + int(uuid.uuid4().int % 90000))

		branch.set(numbers.BRANCH_NUMBER, chosen)
		branch.save()

		self.assertEqual(numbers.series_for(made["pos_profile"]), f"{chosen}-01-.######")

	def test_a_branch_number_already_taken_is_refused_and_says_whose_it_is(self):
		taken_by = _branch_with_a_till()["branch"]
		taken = frappe.db.get_value("Branch", taken_by, numbers.BRANCH_NUMBER)
		other = frappe.get_doc("Branch", _branch_with_a_till()["branch"])

		other.set(numbers.BRANCH_NUMBER, taken)
		with self.assertRaises(frappe.ValidationError) as refused:
			other.save()

		self.assertIn(taken_by, str(refused.exception))

	def test_a_device_number_already_taken_in_the_branch_is_refused(self):
		"""`1` and `01` are the same terminal number, however they are typed."""
		made = _branch_with_a_till()
		twin = _second_till(made["pos_profile"])

		twin.set(numbers.DEVICE_NUMBER, "1")
		with self.assertRaises(frappe.ValidationError) as refused:
			twin.insert()

		self.assertIn(made["pos_profile"], str(refused.exception))

	def test_the_same_device_number_is_fine_in_another_branch(self):
		first = _branch_with_a_till()
		second = _branch_with_a_till()

		self.assertEqual(
			frappe.db.get_value("POS Profile", first["pos_profile"], numbers.DEVICE_NUMBER),
			frappe.db.get_value("POS Profile", second["pos_profile"], numbers.DEVICE_NUMBER),
		)
		self.assertNotEqual(
			numbers.series_for(first["pos_profile"]), numbers.series_for(second["pos_profile"])
		)

	def test_a_number_that_is_not_a_number_is_refused(self):
		branch = frappe.get_doc("Branch", _branch_with_a_till()["branch"])

		branch.set(numbers.BRANCH_NUMBER, "RIYADH")
		with self.assertRaises(frappe.ValidationError):
			branch.save()

	def test_the_counter_exists_before_the_terminal_has_sold(self):
		"""Two tills making their counter rows at their first sale deadlock on the gap
		(`docs/14` §5.3.1) — so the row is made with the terminal."""
		made = _branch_with_a_till()

		prefix = NamingSeries(numbers.series_for(made["pos_profile"])).get_prefix()

		self.assertEqual(frappe.db.get_value("Series", prefix, "current", order_by="name"), 0)

	def test_a_terminal_from_before_numbers_is_numbered_when_asked(self):
		made = _branch_with_a_till()
		frappe.db.set_value("POS Profile", made["pos_profile"], numbers.DEVICE_NUMBER, None)
		frappe.db.set_value("Branch", made["branch"], numbers.BRANCH_NUMBER, None)

		numbers.number_existing()

		self.assertTrue(frappe.db.get_value("Branch", made["branch"], numbers.BRANCH_NUMBER))
		self.assertEqual(frappe.db.get_value("POS Profile", made["pos_profile"], numbers.DEVICE_NUMBER), "01")

	def test_a_profile_that_is_not_a_till_is_left_alone(self):
		"""An ERPNext POS Profile nobody gave a section keeps ERPNext's own series."""
		made = _branch_with_a_till()
		plain = _second_till(made["pos_profile"])
		plain.restaurant_section = None
		plain.insert()

		self.assertFalse(plain.get(numbers.DEVICE_NUMBER))
		self.assertIsNone(numbers.series_for(plain.name))


class TheInvoiceCarriesTheNumber(ReturnTestBase):
	def _prefix(self) -> str:
		branch = branch_of_profile(self.profile)
		return "{}-{}-".format(
			frappe.db.get_value("Branch", branch, numbers.BRANCH_NUMBER),
			frappe.db.get_value("POS Profile", self.profile, numbers.DEVICE_NUMBER),
		)

	def test_a_sale_is_numbered_branch_terminal_count(self):
		order = self._paid()

		self.assertTrue(order.sales_invoice.startswith(self._prefix()), order.sales_invoice)
		self.assertRegex(order.sales_invoice, r"^\d+-\d{2}-\d{6}$")

	def test_two_sales_on_a_terminal_follow_one_another(self):
		first = self._paid().sales_invoice
		second = self._paid().sales_invoice

		self.assertEqual(int(second.rsplit("-", 1)[1]), int(first.rsplit("-", 1)[1]) + 1)

	def test_a_credit_note_counts_on_the_terminals_own_series(self):
		"""One unbroken sequence per device, sales and returns alike."""
		order = self._paid()

		result = returns_service.create_return(
			order, items=[{"row": self._row(order), "qty": 1}], reason_code=REASON
		)

		self.assertTrue(result["credit_note"].startswith(self._prefix()), result["credit_note"])
		self.assertEqual(
			int(result["credit_note"].rsplit("-", 1)[1]), int(order.sales_invoice.rsplit("-", 1)[1]) + 1
		)

	def test_a_terminal_that_has_sold_keeps_its_number(self):
		self._paid()
		profile = frappe.get_doc("POS Profile", self.profile)

		profile.set(numbers.DEVICE_NUMBER, "77")
		with self.assertRaises(frappe.ValidationError):
			profile.save()

	def test_a_branch_that_has_sold_keeps_its_number(self):
		self._paid()
		branch = frappe.get_doc("Branch", branch_of_profile(self.profile))

		branch.set(numbers.BRANCH_NUMBER, "888888")
		with self.assertRaises(frappe.ValidationError):
			branch.save()


class OrdersCountOnTheTerminalToo(ReturnTestBase):
	"""`D-310` — opening a bill does not wait for another till's bill either."""

	def test_an_order_is_named_on_its_terminals_series(self):
		order = self._order()

		series = numbers.series_for(self.profile)
		self.assertTrue(order.name.startswith("RO-" + series.split(".")[0]), order.name)
		self.assertRegex(order.name, r"^RO-\d+-\d{2}-\d{6}$")

	def test_two_orders_on_a_terminal_follow_one_another(self):
		first, second = self._order().name, self._order().name

		self.assertEqual(int(second.rsplit("-", 1)[1]), int(first.rsplit("-", 1)[1]) + 1)

	def test_the_order_counter_exists_with_the_terminal(self):
		made = _branch_with_a_till()

		prefix = NamingSeries("RO-" + numbers.series_for(made["pos_profile"])).get_prefix()

		self.assertEqual(frappe.db.get_value("Series", prefix, "current", order_by="name"), 0)


class WhatNobodyReadsHasNoCounter(ReturnTestBase):
	"""`D-310` — a ticket, an activity row and a print job each took a number from a
	counter the whole company shared, on every tap. Nobody ever read those numbers."""

	def test_activity_rows_tickets_and_print_jobs_are_not_numbered(self):
		order = self._paid()

		rows = frappe.get_all("POS Order Activity", filters={"restaurant_order": order.name}, pluck="name")
		self.assertTrue(rows, "paying a bill is on its story")
		for name in rows:
			self.assertFalse(name.startswith("ACT-"), name)

		for doctype in ("POS Order Activity", "Kitchen Order Ticket", "POS Print Job"):
			meta = frappe.get_meta(doctype)
			self.assertEqual(meta.autoname, "hash", doctype)
			self.assertIsNone(meta.get_field("naming_series"), doctype)

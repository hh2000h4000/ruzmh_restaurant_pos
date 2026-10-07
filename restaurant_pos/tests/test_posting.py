# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The till's sales reach the books when they are posted, and only then (`D-313`).

Every figure here was first measured on the rehearsal site against the till
writing its ledgers at each sale (`docs/14`): the same cash, the same revenue,
the same VAT, the same stock — in a handful of rows instead of thousands. These
keep it that way on the real code.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, flt, getdate, nowdate

from restaurant_pos.tests.test_order import BRANCH, CASHIER, ITEM
from restaurant_pos.tests.test_recipes import COST_OF_ONE, RECIPE, RecipeTestBase, _drop_bundle
from restaurant_pos.utils import posting, returns
from restaurant_pos.utils.sale_doc import POSTED_ENTRY, SALE

REASON = "goods_returned"


def _ledger(voucher: str) -> dict[str, float]:
	"""account type or root -> debit minus credit, on one voucher."""
	out: dict[str, float] = {}
	for row in frappe.get_all(
		"GL Entry", filters={"voucher_no": voucher, "is_cancelled": 0}, fields=["account", "debit", "credit"]
	):
		kind = frappe.get_cached_value("Account", row.account, "account_type") or frappe.get_cached_value(
			"Account", row.account, "root_type"
		)
		out[kind] = flt(out.get(kind, 0) + flt(row.debit) - flt(row.credit), 2)
	return out


class PostingTestBase(RecipeTestBase):
	def _post(self):
		names = posting.post_branch(BRANCH)
		return [frappe.get_doc(posting.BATCH, name) for name in names]

	def _stock_moved(self, voucher: str) -> dict[str, float]:
		"""What each item did in the warehouse on one stock document of a batch."""
		moved: dict[str, float] = {}
		for row in frappe.get_all(
			"Stock Ledger Entry",
			filters={"voucher_no": voucher, "is_cancelled": 0},
			fields=["item_code", "actual_qty"],
		):
			moved[row.item_code] = flt(moved.get(row.item_code, 0) + flt(row.actual_qty), 3)
		return moved


class ASaleReachesTheBooksWhenItIsPosted(PostingTestBase):
	def test_one_sale_is_one_batch_posted_whole(self):
		order = self._sold(qty=2)

		(batch,) = self._post()

		self.assertEqual(batch.status, "Posted", batch.error)
		self.assertEqual((batch.accounting_status, batch.stock_status), ("Posted", "Posted"))
		self.assertEqual(batch.invoices, 1)
		self.assertEqual(getdate(batch.posting_date), getdate(nowdate()))
		self.assertEqual(frappe.db.get_value(SALE, order.sales_invoice, "rpos_posting_batch"), batch.name)

	def test_the_money_lands_where_the_sale_said(self):
		order = self._sold(qty=2)
		invoice = frappe.get_doc(SALE, order.sales_invoice)

		(batch,) = self._post()

		entry = frappe.get_doc(POSTED_ENTRY, batch.sales_invoice)
		self.assertEqual((entry.docstatus, entry.is_consolidated, entry.update_stock), (1, 1, 0))
		self.assertAlmostEqual(entry.net_total, invoice.net_total, places=2)
		self.assertAlmostEqual(entry.total_taxes_and_charges, invoice.total_taxes_and_charges, places=2)

		ledger = _ledger(entry.name)
		paid = flt(invoice.rounded_total or invoice.grand_total)
		self.assertAlmostEqual(ledger.get("Cash", 0), paid, places=2)
		self.assertAlmostEqual(-ledger.get("Tax", 0), invoice.total_taxes_and_charges, places=2)
		self.assertAlmostEqual(ledger.get("Receivable", 0), 0, places=2, msg="paid in full: nothing is owed")

	def test_the_kitchen_s_ingredients_leave_the_warehouse_once(self):
		self._sold(qty=2)

		(batch,) = self._post()

		self.assertEqual(
			self._stock_moved(batch.stock_issue),
			{code: flt(-2 * qty, 3) for code, _uom, qty, _rate in RECIPE},
		)
		cost = sum(
			flt(row.stock_value_difference)
			for row in frappe.get_all(
				"Stock Ledger Entry",
				filters={"voucher_no": batch.stock_issue},
				fields=["stock_value_difference"],
			)
		)
		self.assertAlmostEqual(-cost, 2 * COST_OF_ONE, places=2)

	def test_a_day_of_sales_is_one_entry_and_one_stock_issue(self):
		invoices = [frappe.get_doc(SALE, self._sold(qty=qty).sales_invoice) for qty in (1, 2, 3)]

		(batch,) = self._post()

		self.assertEqual(batch.invoices, 3)
		entry = frappe.get_doc(POSTED_ENTRY, batch.sales_invoice)
		self.assertAlmostEqual(entry.net_total, sum(doc.net_total for doc in invoices), places=2)
		self.assertAlmostEqual(
			entry.total_taxes_and_charges, sum(doc.total_taxes_and_charges for doc in invoices), places=2
		)
		self.assertEqual(
			self._stock_moved(batch.stock_issue),
			{code: flt(-6 * qty, 3) for code, _uom, qty, _rate in RECIPE},
		)

	def test_what_was_paid_is_never_written_off(self):
		"""Each invoice rounds its own net and tax; the sums miss what was paid by a few
		halalas. That is rounding — and ERPNext, left to itself, wrote it off as uncollected."""
		for qty in (1, 2, 3, 1, 2):
			self._sold(qty=qty)

		(batch,) = self._post()

		entry = frappe.get_doc(POSTED_ENTRY, batch.sales_invoice)
		self.assertAlmostEqual(entry.write_off_amount, 0, places=2)
		self.assertAlmostEqual(entry.outstanding_amount, 0, places=2)

	def test_what_the_posting_made_names_its_batch(self):
		self._sold(qty=1)

		(batch,) = self._post()

		self.assertEqual(
			frappe.db.get_value(POSTED_ENTRY, batch.sales_invoice, "rpos_posting_batch"), batch.name
		)
		self.assertEqual(
			frappe.db.get_value("Stock Entry", batch.stock_issue, "rpos_posting_batch"), batch.name
		)

	def test_the_recipe_is_read_off_the_bill_not_off_the_recipe_card(self):
		"""Measured: ERPNext's own consolidation rebuilt the recipe from today's card and
		took twice the cheese for burgers sold at one slice (`docs/14` §4.2)."""
		self._sold(qty=2)
		card = frappe.get_doc("Product Bundle", ITEM)
		for row in card.items:
			row.qty = flt(row.qty) * 2
		card.save(ignore_permissions=True)

		(batch,) = self._post()

		self.assertEqual(
			self._stock_moved(batch.stock_issue),
			{code: flt(-2 * qty, 3) for code, _uom, qty, _rate in RECIPE},
		)


class PostingIsSafeToRunAgain(PostingTestBase):
	def test_nothing_to_post_makes_nothing(self):
		self.assertEqual(self._post(), [])

	def test_a_second_run_posts_nothing_twice(self):
		self._sold(qty=2)
		(batch,) = self._post()
		entries = frappe.db.count(POSTED_ENTRY, {"rpos_posting_batch": batch.name})
		issues = frappe.db.count("Stock Entry", {"rpos_posting_batch": batch.name})

		self.assertEqual(self._post(), [])
		posting.run(batch.name)

		self.assertEqual(frappe.db.count(POSTED_ENTRY, {"rpos_posting_batch": batch.name}), entries)
		self.assertEqual(frappe.db.count("Stock Entry", {"rpos_posting_batch": batch.name}), issues)

	def test_one_posting_of_a_branch_at_a_time(self):
		"""Two postings of one branch deadlocked on each other's claims; the branch's row
		is the queue, so the second waits and then finds nothing left to do."""
		real = frappe.db.get_value
		locked = []

		def watching(doctype, *args, **kwargs):
			if kwargs.get("for_update"):
				locked.append((doctype, args[0] if args else None))
			return real(doctype, *args, **kwargs)

		with patch.object(frappe.db, "get_value", side_effect=watching):
			self._post()

		self.assertEqual(locked[0], ("Branch", BRANCH), "taken before anything is claimed")

	def test_a_sale_rung_up_after_the_claim_waits_for_the_next_batch(self):
		self._sold(qty=1)
		(first,) = self._post()

		later = self._sold(qty=1)
		(second,) = self._post()

		self.assertNotEqual(first.name, second.name)
		self.assertEqual(frappe.db.get_value(SALE, later.sales_invoice, "rpos_posting_batch"), second.name)
		self.assertEqual(second.invoices, 1)

	def test_stock_that_fails_leaves_the_accounts_posted_and_nothing_half_done(self):
		"""Revenue does not wait for the stock ledger (`docs/14` §6.2)."""
		self._sold(qty=2)

		with patch.object(posting, "_stock_entry", side_effect=frappe.ValidationError("the shelf is wrong")):
			(batch,) = self._post()

		self.assertEqual(batch.status, "Failed")
		self.assertEqual((batch.accounting_status, batch.stock_status), ("Posted", "Failed"))
		self.assertIn("the shelf is wrong", batch.error)
		self.assertTrue(batch.sales_invoice)
		self.assertFalse(batch.stock_issue)
		self.assertEqual(frappe.db.count("Stock Entry", {"rpos_posting_batch": batch.name}), 0)

	def test_and_trying_again_posts_the_stock_once_and_the_accounts_not_at_all(self):
		self._sold(qty=2)
		with patch.object(posting, "_stock_entry", side_effect=frappe.ValidationError("the shelf is wrong")):
			(failed,) = self._post()

		(batch,) = self._post()

		self.assertEqual(batch.name, failed.name)
		self.assertEqual(batch.status, "Posted", batch.error)
		self.assertEqual(batch.attempts, 2)
		self.assertFalse(batch.error)
		self.assertEqual(batch.sales_invoice, failed.sales_invoice, "the entry made the first time")
		self.assertEqual(frappe.db.count(POSTED_ENTRY, {"rpos_posting_batch": batch.name}), 1)
		self.assertEqual(
			self._stock_moved(batch.stock_issue),
			{code: flt(-2 * qty, 3) for code, _uom, qty, _rate in RECIPE},
		)

	def test_an_ingredient_with_no_cost_is_named_before_anything_is_taken(self):
		code = "RPOS-TEST-NOCOST"
		self._ingredient(code, "Nos")
		card = frappe.get_doc("Product Bundle", ITEM)
		card.append("items", {"item_code": code, "qty": 1})
		card.save(ignore_permissions=True)
		self._sold(qty=1)

		(batch,) = self._post()

		self.assertEqual((batch.accounting_status, batch.stock_status), ("Posted", "Failed"))
		self.assertIn(code, batch.error)
		self.assertEqual(frappe.db.count("Stock Entry", {"rpos_posting_batch": batch.name}), 0)


class ReturnsArePostedAsReturns(PostingTestBase):
	def _returned(self, order, qty: float = 1):
		"""Back on the shelf: said outright, because a dish is waste unless the cashier says not."""
		row = returns.returnable(order)["items"][0]["row"]
		return returns.create_return(order, items=[{"row": row, "qty": qty, "wasted": 0}], reason_code=REASON)

	def test_a_sale_and_its_return_are_two_entries(self):
		order = self._sold(qty=2)
		refund = self._returned(order, qty=1)

		(batch,) = self._post()

		self.assertEqual(batch.status, "Posted", batch.error)
		self.assertTrue(batch.sales_invoice and batch.credit_note)
		note = frappe.get_doc(POSTED_ENTRY, batch.credit_note)
		credit = frappe.get_doc(SALE, refund["credit_note"])
		self.assertEqual((note.is_return, note.is_consolidated), (1, 1))
		self.assertAlmostEqual(note.grand_total, credit.grand_total, places=2)
		self.assertLess(note.grand_total, 0)

	def test_a_day_with_only_a_refund_posts_as_a_credit_note(self):
		"""The prototype put sales and returns on one invoice, and a day of only a refund
		failed on a negative total (`docs/14` §8)."""
		order = self._sold(qty=2)
		self._post()

		self._returned(order, qty=1)
		(batch,) = self._post()

		self.assertEqual(batch.status, "Posted", batch.error)
		self.assertFalse(batch.sales_invoice)
		self.assertTrue(batch.credit_note)

	def test_what_came_back_goes_back_on_the_shelf(self):
		order = self._sold(qty=2)
		self._post()

		self._returned(order, qty=1)
		(batch,) = self._post()

		self.assertEqual(
			self._stock_moved(batch.stock_receipt), {code: flt(qty, 3) for code, _uom, qty, _rate in RECIPE}
		)


class WhatCameBackGoesOnTheShelfOrInTheBin(PostingTestBase):
	"""`D-315` — a bottle of water is sold again; a burger is not."""

	COLA = "RPOS-TEST-POST-COLA"

	def setUp(self):
		super().setUp()
		# Required by the settings; a site that has been migrated has one.
		self._waste_account()

	def _cola(self) -> None:
		"""Something sold as it came: kept in stock as itself, with a price on the till's list."""
		self._ingredient(self.COLA, "Nos")
		self._receive(self.COLA, 50, 2.0)
		price_list = frappe.db.get_value("POS Profile", self.profile, "selling_price_list")
		if not frappe.db.exists("Item Price", {"item_code": self.COLA, "price_list": price_list}):
			frappe.get_doc(
				{
					"doctype": "Item Price",
					"item_code": self.COLA,
					"price_list": price_list,
					"price_list_rate": 5,
				}
			).insert(ignore_permissions=True)

	def _waste_account(self) -> str:
		from restaurant_pos.setup import waste_account

		return waste_account.setup()

	def _returned(self, order, **said):
		row = returns.returnable(order)["items"][0]["row"]
		return returns.create_return(order, items=[{"row": row, "qty": 1, **said}], reason_code=REASON)

	def test_a_dish_is_waste_and_a_thing_sold_as_it_came_is_not_unless_told_otherwise(self):
		self._cola()

		self.assertTrue(returns.wasted_by_default(ITEM), "a burger sent back is not put back in the fridge")
		self.assertFalse(returns.wasted_by_default(self.COLA), "a sealed can goes back on the shelf")

	def test_the_screen_is_told_which_lines_to_ask_about_and_not_what_to_answer(self):
		"""`D-327` — a guest who cancels before the kitchen starts has wasted nothing.

		The till asks about a line that took stock and presumes nothing; the
		answer by item kind is only for a caller with no cashier in front of it.
		"""
		order = self._sold(qty=1)

		line = returns.returnable(order)["items"][0]

		self.assertTrue(line["moves_stock"], "the burger took its ingredients")
		self.assertNotIn("wasted", line)

	def test_a_line_that_took_no_stock_is_not_asked_about(self):
		_drop_bundle()
		order = self._sold(qty=1)

		self.assertFalse(returns.returnable(order)["items"][0]["moves_stock"])

	def test_a_returned_dish_stays_out_of_the_warehouse(self):
		order = self._sold(qty=2)
		self._post()

		refund = self._returned(order)
		(batch,) = self._post()

		self.assertEqual(batch.status, "Posted", batch.error)
		self.assertFalse(batch.stock_receipt, "nothing goes back on the shelf")
		note = frappe.get_doc(SALE, refund["credit_note"])
		self.assertEqual([row.rpos_wasted for row in note.items], [1])

	def test_and_its_cost_leaves_cost_of_sales_for_the_waste_account(self):
		account = self._waste_account()
		order = self._sold(qty=2)
		self._post()

		self._returned(order)
		(batch,) = self._post()

		self.assertTrue(batch.waste_entry, batch.error)
		rows = frappe.get_all(
			"GL Entry",
			filters={"voucher_no": batch.waste_entry, "is_cancelled": 0},
			fields=["account", "debit", "credit"],
		)
		waste = sum(flt(row.debit) - flt(row.credit) for row in rows if row.account == account)
		elsewhere = sum(flt(row.debit) - flt(row.credit) for row in rows if row.account != account)
		self.assertAlmostEqual(waste, COST_OF_ONE, places=2, msg="one burger, at what it cost when sold")
		self.assertAlmostEqual(elsewhere, -COST_OF_ONE, places=2, msg="and out of cost of sales")
		self.assertEqual(
			frappe.db.get_value("Journal Entry", batch.waste_entry, "rpos_posting_batch"), batch.name
		)

	def test_the_cashier_can_say_a_dish_went_back_on_the_shelf(self):
		order = self._sold(qty=2)
		self._post()

		self._returned(order, wasted=0)
		(batch,) = self._post()

		self.assertFalse(batch.waste_entry)
		self.assertEqual(
			self._stock_moved(batch.stock_receipt), {code: flt(qty, 3) for code, _uom, qty, _rate in RECIPE}
		)

	def test_a_sale_and_its_wasted_return_in_one_day_cost_the_waste_too(self):
		"""The sale's cost is written when its stock is taken — in this same posting — and
		the waste entry reads it a step later."""
		self._waste_account()
		order = self._sold(qty=2)
		self._returned(order)

		(batch,) = self._post()

		self.assertEqual(batch.status, "Posted", batch.error)
		self.assertTrue(batch.waste_entry)
		self.assertAlmostEqual(
			frappe.db.get_value("Journal Entry", batch.waste_entry, "total_debit"), COST_OF_ONE, places=2
		)

	def test_with_no_waste_account_the_day_s_stock_waits_and_says_what_for(self):
		"""Required (the owner's call): waste left in cost of sales hides inside the food cost
		of what did sell. The accounts are posted; the stock waits for the setting."""
		chosen = frappe.db.get_single_value("Restaurant POS Settings", "waste_account")
		frappe.db.set_single_value("Restaurant POS Settings", "waste_account", None)
		self.addCleanup(frappe.db.set_single_value, "Restaurant POS Settings", "waste_account", chosen)
		order = self._sold(qty=2)
		self._post()

		self._returned(order)
		(batch,) = self._post()

		self.assertEqual((batch.accounting_status, batch.stock_status), ("Posted", "Failed"))
		self.assertIn("Waste Account", batch.error)
		self.assertFalse(batch.waste_entry)

	def test_and_posts_once_the_account_is_chosen(self):
		chosen = self._waste_account()
		frappe.db.set_single_value("Restaurant POS Settings", "waste_account", None)
		order = self._sold(qty=2)
		self._post()
		self._returned(order)
		(failed,) = self._post()

		frappe.db.set_single_value("Restaurant POS Settings", "waste_account", chosen)
		(batch,) = self._post()

		self.assertEqual(batch.name, failed.name)
		self.assertEqual(batch.status, "Posted", batch.error)
		self.assertTrue(batch.waste_entry)

	def test_the_settings_cannot_be_saved_without_a_waste_account(self):
		field = frappe.get_meta("Restaurant POS Settings").get_field("waste_account")

		self.assertEqual(field.reqd, 1)


class ADayIsACalendarDate(PostingTestBase):
	def test_sales_either_side_of_midnight_are_two_batches_each_on_its_date(self):
		"""Measured: one batch for a whole service put all of its revenue and VAT on the
		day it was posted (`docs/14` §6.4)."""
		yesterday = add_days(nowdate(), -1)
		late = self._sold(qty=1)
		frappe.db.set_value(SALE, late.sales_invoice, {"posting_date": yesterday, "posting_time": "23:40:00"})
		self._sold(qty=2)

		batches = self._post()

		self.assertEqual(
			sorted(str(getdate(batch.posting_date)) for batch in batches), sorted([yesterday, nowdate()])
		)
		for batch in batches:
			self.assertEqual(batch.accounting_status, "Posted", batch.error)
			self.assertEqual(
				getdate(frappe.db.get_value(POSTED_ENTRY, batch.sales_invoice, "posting_date")),
				getdate(batch.posting_date),
			)


class TheDayCloseSendsItsSalesToTheBooks(PostingTestBase):
	def test_closing_the_day_queues_the_posting(self):
		from restaurant_pos.utils import shift as shift_service

		day = frappe.db.get_value("POS Profile", self.profile, "restaurant_shift")
		with patch.object(frappe, "enqueue") as queued:
			shift_service.close_day(shift_name=day, force=True, pos_profile=self.profile)

		jobs = [call for call in queued.call_args_list if call.args and "posting.post_branch" in call.args[0]]
		self.assertEqual(len(jobs), 1)
		self.assertEqual(jobs[0].kwargs["branch"], BRANCH)
		self.assertEqual(jobs[0].kwargs["shift"], day)
		self.assertTrue(jobs[0].kwargs["enqueue_after_commit"])


class APostingThatFailsIsSaidAndTriedAgain(PostingTestBase):
	"""`D-317` — whoever closed the day has gone home; the failure must reach somebody."""

	WRONG = frappe.ValidationError("the shelf is wrong")

	def _bells(self, batch) -> int:
		return frappe.db.count(
			"Notification Log", {"document_type": posting.BATCH, "document_name": batch.name}
		)

	def _errors(self, batch) -> int:
		return frappe.db.count("Error Log", {"method": ("like", f"%{batch.name}%")})

	def _failed(self):
		self._sold(qty=1)
		with patch.object(posting, "_stock_entry", side_effect=self.WRONG):
			(batch,) = self._post()
		return batch

	def test_it_rings_the_office_bell_with_the_reason(self):
		batch = self._failed()

		logs = frappe.get_all(
			"Notification Log",
			filters={"document_type": posting.BATCH, "document_name": batch.name},
			fields=["for_user", "type", "email_content"],
		)
		self.assertTrue(logs, "nobody was told")
		self.assertEqual({log.type for log in logs}, {"Alert"})  # Alert sends no email
		self.assertIn("the shelf is wrong", logs[0].email_content)
		watchers = set(frappe.get_all("Has Role", filters={"role": ("in", posting.WATCHERS)}, pluck="parent"))
		self.assertLessEqual({log.for_user for log in logs}, watchers)

	def test_the_same_failure_is_said_once_however_often_it_is_retried(self):
		batch = self._failed()
		bells, errors = self._bells(batch), self._errors(batch)

		with patch.object(posting, "_stock_entry", side_effect=self.WRONG):
			posting.retry_unfinished()

		self.assertEqual(frappe.db.get_value(posting.BATCH, batch.name, "attempts"), 2)
		self.assertEqual(self._bells(batch), bells)
		self.assertEqual(self._errors(batch), errors)

	def test_a_different_failure_is_said_again(self):
		batch = self._failed()
		bells = self._bells(batch)

		with patch.object(
			posting, "_stock_entry", side_effect=frappe.ValidationError("the period is closed")
		):
			posting.retry_unfinished()

		self.assertGreater(self._bells(batch), bells)

	def test_the_hourly_retry_finishes_it_once_the_cause_is_gone(self):
		batch = self._failed()

		posting.retry_unfinished()

		batch.reload()
		self.assertEqual(batch.status, "Posted", batch.error)
		self.assertTrue(batch.stock_issue)

	def test_the_hourly_retry_claims_nothing_of_a_day_still_open(self):
		order = self._sold(qty=1)

		posting.retry_unfinished()

		self.assertFalse(frappe.db.get_value(SALE, order.sales_invoice, "rpos_posting_batch"))

	def test_post_now_queues_the_branch_once(self):
		from restaurant_pos.api import posting as api

		with patch.object(frappe, "enqueue") as queued:
			api.post_now(BRANCH)

		(job,) = queued.call_args_list
		self.assertIn("posting.post_branch", job.args[0])
		self.assertEqual(job.kwargs["branch"], BRANCH)
		self.assertTrue(job.kwargs["deduplicate"])
		self.assertIn(BRANCH, job.kwargs["job_id"])

	def test_a_cashier_cannot_ask_for_a_posting(self):
		from restaurant_pos.api import posting as api

		frappe.set_user(CASHIER)
		try:
			with patch.object(frappe, "enqueue") as queued:
				self.assertRaises(frappe.PermissionError, api.post_now, BRANCH)
			queued.assert_not_called()
		finally:
			frappe.set_user("Administrator")


class WhatTheFirstTrialFound(PostingTestBase):
	"""`D-325`."""

	def _no_negative_stock(self):
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 0)
		frappe.db.value_cache = {}

	def test_everything_that_is_short_is_named_at_once(self):
		"""ERPNext names the first and stops: four ingredients took the owner three postings."""
		self._no_negative_stock()
		self._sold(qty=1)
		gone = [code for code, _uom, _qty, _rate in RECIPE][:2]
		for code in gone:
			frappe.db.set_value("Bin", {"item_code": code, "warehouse": self.warehouse}, "actual_qty", 0)

		(batch,) = self._post()

		self.assertEqual((batch.accounting_status, batch.stock_status), ("Posted", "Failed"))
		for code in gone:
			self.assertIn(code, batch.error)
		self.assertEqual(frappe.db.count("Stock Entry", {"rpos_posting_batch": batch.name}), 0)

	def test_where_stock_may_go_below_zero_nothing_is_asked(self):
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)
		frappe.db.value_cache = {}
		self.addCleanup(frappe.db.set_single_value, "Stock Settings", "allow_negative_stock", 0)

		posting._assert_on_the_shelf({(RECIPE[0][0], self.warehouse): 10_000})

	def test_the_reason_is_kept_in_the_site_s_language(self):
		"""A background job speaks English unless told; an Arabic site read an English reason."""
		before = frappe.db.get_single_value("System Settings", "language")
		frappe.db.set_single_value("System Settings", "language", "ar")
		self.addCleanup(frappe.db.set_single_value, "System Settings", "language", before)
		self._no_negative_stock()
		self._sold(qty=1)
		frappe.db.set_value("Bin", {"item_code": RECIPE[0][0], "warehouse": self.warehouse}, "actual_qty", 0)
		spoken = frappe.local.lang

		(batch,) = self._post()

		self.assertNotIn("Not enough stock", batch.error)
		self.assertIn(RECIPE[0][0], batch.error)
		self.assertEqual(frappe.local.lang, spoken, "and the caller's language is left as it was")

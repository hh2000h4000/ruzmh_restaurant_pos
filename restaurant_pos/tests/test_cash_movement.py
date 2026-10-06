# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Notes in and out of a drawer for something that is not a sale (`D-245`).

The whole point of the record is that the count and the expectation agree
afterwards, so that is what is asserted first: money taken out lowers what the
drawer is expected to hold by exactly that much, and money put in raises it.
The rest are the doors around it — the shift gate, the branch, the permission
and the manager's PIN behind it, and the fact that the row cannot be edited or
deleted once written.

Refs: FR-8.3, BR-041, BR-044, D-245
"""

import frappe
from frappe.utils import flt

from restaurant_pos.setup import cash_accounts
from restaurant_pos.tests.test_payment import CASH, PaymentTestBase
from restaurant_pos.utils import cash_movement
from restaurant_pos.utils import shift as shifts
from restaurant_pos.utils.permissions import issue_override_token
from restaurant_pos.utils.sale_doc import SALE

REASON = "bag of ice"


class CashMovementTestBase(PaymentTestBase):
	def _till(self) -> str:
		return shifts.selling_till(self.profile).name

	def _expected(self) -> float:
		summary = shifts.summarise_till(self._till())
		return flt(summary["till_expected"])

	def _move(self, direction: str, amount: float, **kwargs) -> dict:
		return cash_movement.record(self.profile, direction=direction, amount=amount, reason=REASON, **kwargs)


class TestTheDrawerAgreesAfterwards(CashMovementTestBase):
	def test_money_taken_out_lowers_what_the_drawer_should_hold(self):
		before = self._expected()

		self._move("out", 30)

		self.assertAlmostEqual(self._expected(), before - 30, places=2)

	def test_money_put_in_raises_it(self):
		before = self._expected()

		self._move("in", 50)

		self.assertAlmostEqual(self._expected(), before + 50, places=2)

	def test_a_sale_and_a_movement_both_land_in_the_same_figure(self):
		before = self._expected()

		order = self._payable_order(qty=1)
		self._pay(order)
		self._move("out", 20)

		paid = flt(frappe.db.get_value(SALE, order.sales_invoice, "grand_total"))
		self.assertAlmostEqual(self._expected(), before + paid - 20, places=2)

	def test_it_is_listed_on_the_drawer_s_report_with_its_reason(self):
		"""A difference the count can explain is not a difference."""
		self._move("out", 15)

		listed = shifts.summarise_till(self._till())["movements"]

		self.assertTrue(any(row["reason"] == REASON and row["amount"] == 15 for row in listed))

	def test_it_touches_only_its_own_payment_method(self):
		card = _a_second_method(self.profile)
		if not card:
			self.skipTest("this terminal offers one payment method")

		before = {row["method"]: row["expected"] for row in shifts.summarise_till(self._till())["by_method"]}

		self._move("out", 25, mode_of_payment=CASH)

		after = {row["method"]: row["expected"] for row in shifts.summarise_till(self._till())["by_method"]}
		self.assertAlmostEqual(after[CASH], before[CASH] - 25, places=2)
		self.assertAlmostEqual(after[card], before.get(card, 0), places=2)


class TestACountedDrawerIsClosedToIt(CashMovementTestBase):
	"""Alone in its class: closing the till is not undone between tests.

	`FrappeTestCase` rolls back once per class, so a drawer counted here would
	still be counted for every test that ran after it — and each of them would
	fail on "open a shift" for a reason that has nothing to do with what it
	claims to check.
	"""

	def test_nothing_may_move_without_an_open_drawer(self):
		"""`BR-044` — a drawer that has been counted cannot lose notes afterwards."""
		shifts.close_till(opening_entry=self._till(), counted={CASH: 0})

		with self.assertRaises(frappe.ValidationError):
			self._move("out", 10)


class TestTheDoorsAroundIt(CashMovementTestBase):
	def test_zero_and_below_are_refused(self):
		for amount in (0, -5):
			with self.subTest(amount=amount), self.assertRaises(frappe.ValidationError):
				self._move("out", amount)

	def test_a_direction_nobody_offers_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._move("sideways", 10)

	def test_it_will_not_be_written_without_a_reason(self):
		with self.assertRaises(frappe.ValidationError):
			cash_movement.record(self.profile, direction="out", amount=10, reason="   ")

	def test_the_row_is_evidence_and_cannot_be_deleted(self):
		result = self._move("out", 10)

		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("POS Cash Movement", result["movement"])

	def test_it_is_written_into_the_trail(self):
		result = self._move("out", 12)

		self.assertTrue(
			frappe.db.exists(
				"POS Audit Log",
				{"action_type": "cash_out", "details": ("like", f"%{result['movement']}%")},
			)
		)


class TestWhoMayMoveIt(CashMovementTestBase):
	"""Driven as a real cashier: Administrator holds every permission by design."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from restaurant_pos.tests.test_order import _make_cashier

		cls.cashier = _make_cashier()

	def setUp(self):
		super().setUp()
		frappe.set_user(self.cashier)
		frappe.local.rpos_permission_cache = {}

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.rpos_permission_cache = {}
		super().tearDown()

	def test_a_cashier_without_the_permission_is_asked_for_a_manager(self):
		with self.assertRaises(frappe.PermissionError):
			self._move("out", 10)

	def test_a_manager_s_token_lets_it_through_and_carries_their_name(self):
		token = issue_override_token(cash_movement.PERMISSION, "Administrator")

		result = self._move("out", 10, override_token=token)

		self.assertEqual(
			frappe.db.get_value("POS Cash Movement", result["movement"], "approved_by"), "Administrator"
		)


def _a_second_method(pos_profile: str) -> str | None:
	"""Another till method on this terminal, if it offers one."""
	for row in frappe.get_all(
		"POS Payment Method",
		filters={"parent": pos_profile, "parenttype": "POS Profile"},
		pluck="mode_of_payment",
	):
		if row != CASH and not frappe.db.get_value("Mode of Payment", row, "rpos_is_credit"):
			return row
	return None


class TestItReachesTheBooks(CashMovementTestBase):
	"""`D-246` — the reason carries the account, as Toast's pay-out reasons do."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_value("POS Profile", cls.profile, "company")
		cls.account = _an_expense_account(cls.company)
		cash_accounts.setup(cls.company)

	def _with_account(self, account: str | None) -> str:
		"""A reason of our own, so the shipped ones keep whatever the site gave them."""
		title = "RPOS Test Cash Reason"
		if not frappe.db.exists("POS Quick Note", title):
			frappe.get_doc(
				{
					"doctype": "POS Quick Note",
					"title": title,
					"title_ar": title,
					"scope": "cash_reason",
					"is_active": 1,
				}
			).insert(ignore_permissions=True)

		frappe.db.set_value("POS Quick Note", title, "expense_account", account)
		return title

	def _move_for(self, reason: str, direction: str = "out", amount: float = 20) -> str:
		result = cash_movement.record(self.profile, direction=direction, amount=amount, reason=reason)
		return result["movement"]

	def test_a_movement_posts_its_own_entry(self):
		reason = self._with_account(self.account)

		movement = self._move_for(reason)

		entry = frappe.db.get_value("POS Cash Movement", movement, "journal_entry")
		self.assertTrue(entry, "no journal entry was posted")
		self.assertEqual(frappe.db.get_value("Journal Entry", entry, "voucher_type"), "Cash Entry")

	def test_money_out_debits_the_reason_and_credits_the_drawer(self):
		reason = self._with_account(self.account)

		movement = self._move_for(reason, direction="out", amount=20)

		lines = _lines_of(frappe.db.get_value("POS Cash Movement", movement, "journal_entry"))
		self.assertAlmostEqual(lines[self.account]["debit"], 20, places=2)
		self.assertAlmostEqual(sum(row["credit"] for row in lines.values()), 20, places=2)

	def test_money_in_turns_the_entry_around(self):
		reason = self._with_account(self.account)

		movement = self._move_for(reason, direction="in", amount=20)

		lines = _lines_of(frappe.db.get_value("POS Cash Movement", movement, "journal_entry"))
		self.assertAlmostEqual(lines[self.account]["credit"], 20, places=2)

	def test_a_reason_with_no_account_still_moves_the_money_and_says_why_not(self):
		"""The books never hold the drawer hostage."""
		reason = self._with_account(None)
		before = self._expected()

		movement = self._move_for(reason, amount=15)

		row = frappe.db.get_value(
			"POS Cash Movement", movement, ["journal_entry", "posting_note"], as_dict=True
		)
		self.assertIsNone(row.journal_entry)
		self.assertTrue(row.posting_note, "nothing said why it did not post")
		self.assertAlmostEqual(self._expected(), before - 15, places=2)

	def test_the_shipped_reasons_are_given_somewhere_to_land(self):
		"""`D-246` — the user had no idea which accounts to use, so these are made."""
		for title in ("Bought supplies", "Change from the safe"):
			with self.subTest(reason=title):
				if not frappe.db.exists("POS Quick Note", title):
					self.skipTest("this site does not ship the reason")
				self.assertTrue(frappe.db.get_value("POS Quick Note", title, "expense_account"))


def _an_expense_account(company: str) -> str:
	return frappe.get_all(
		"Account",
		filters={"company": company, "root_type": "Expense", "is_group": 0},
		pluck="name",
		limit=1,
	)[0]


def _lines_of(entry: str) -> dict[str, dict]:
	rows = frappe.get_all(
		"Journal Entry Account",
		filters={"parent": entry},
		fields=["account", "debit_in_account_currency", "credit_in_account_currency"],
	)
	return {
		row.account: {
			"debit": flt(row.debit_in_account_currency),
			"credit": flt(row.credit_in_account_currency),
		}
		for row in rows
	}

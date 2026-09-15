# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The business day, and the tills that work inside it.

Two rules carry the weight here.

**Credit never enters the count** (D-029, D-046). A delivery platform already
took the customer's money, so it must not be counted into the cash a drawer is
expected to hold — otherwise every close shows a shortfall the size of the day's
app orders and the variance figure stops meaning anything.

**The two levels are separate** (D-047). A till session is one cashier and one
drawer; a business day is the branch. Closing one is not closing the other.

Refs: FR-8.1..8.3, BR-040..BR-045, D-029, D-046, D-047
"""

from unittest.mock import patch

import frappe
from frappe.utils import flt, now_datetime

from restaurant_pos.tests.test_order import BRANCH, ITEM, OrderTestBase
from restaurant_pos.tests.test_payment import CASH, _ensure_fiscal_year
from restaurant_pos.utils import order as orders
from restaurant_pos.utils import payment, returns
from restaurant_pos.utils import shift as service

#: Somebody other than whoever opened the drawer. Written onto the bill after it
#: is paid — the one field the drawer's count reads to decide whose sale it was.
SECOND_CASHIER = "rpos-second-cashier@example.com"


class ShiftTestBase(OrderTestBase):
	def setUp(self):
		self.settlement = frappe.db.get_value("Branch", BRANCH, "settlement_required")
		self.shift_type = frappe.db.get_value("Branch", BRANCH, "shift_type")
		self.finish_orders = frappe.db.get_value("Branch", BRANCH, "close_open_orders_with_day")
		self.warn_at = frappe.db.get_value("Branch", BRANCH, "carried_orders_warning_at")

		# **Set, not merely remembered.** These tests assert what a branch does at
		# closing time, and reading the answer off the site made the assertion
		# depend on what an earlier run happened to leave committed there — which
		# it did: the test site held `0`, so four tests about a day that *refuses*
		# to close ran against a branch that allows it, and the whole suite went
		# red while the module alone passed. A test that owns its rule sets it
		# (`D-155` — the same lesson, one field over).
		frappe.db.set_value(
			"Branch", BRANCH, {"close_open_orders_with_day": 1, "carried_orders_warning_at": 100}
		)
		self._clear()

	def tearDown(self):
		frappe.db.set_value(
			"Branch",
			BRANCH,
			{
				"settlement_required": self.settlement,
				"shift_type": self.shift_type or "single",
				# Restored, or a test that turned it off leaves every later one
				# closing days over open bills without meaning to.
				"close_open_orders_with_day": self.finish_orders,
				"carried_orders_warning_at": self.warn_at,
			},
		)
		self._clear()
		# The suite's other modules expect the terminal to be selling.
		from restaurant_pos.tests.test_order import _ensure_shift

		_ensure_shift(self.profile)

	def _clear(self) -> None:
		"""Leave no open day or drawer behind for the next test to trip over."""
		for name in frappe.get_all(
			"POS Opening Entry", filters={"pos_profile": self.profile, "status": "Open"}, pluck="name"
		):
			frappe.db.set_value("POS Opening Entry", name, "status", "Closed")

		for name in frappe.get_all(
			"Restaurant Shift", filters={"branch": BRANCH, "status": "open"}, pluck="name"
		):
			frappe.db.set_value("Restaurant Shift", name, "status", "closed")

	def _sold_by(self, cashier: str):
		"""A real sale, paid in cash, filed under ``cashier`` — the name the counts read."""
		_ensure_fiscal_year()
		order = self._order()
		orders.add_item(order, item=ITEM, qty=1)
		order.reload()
		payment.process_payment(order, payments=[{"method": CASH, "amount": order.total_amount}])
		frappe.db.set_value("Restaurant Order", order.name, "cashier", cashier, update_modified=False)
		return frappe.get_doc("Restaurant Order", order.name)

	def _opened(self, shift_type: str) -> str:
		frappe.db.set_value("Branch", BRANCH, "shift_type", shift_type)
		return service.open_till(pos_profile=self.profile, opening_floats={"Cash": 100})["entry"]

	def _refund_one(self, order) -> dict:
		row = frappe.db.get_value("Sales Invoice Item", {"parent": order.sales_invoice}, "name")
		return returns.create_return(order, items=[{"row": row, "qty": 1}], reason_code="goods_returned")


class TestTheFinancialReport(ShiftTestBase):
	"""`D-219` — what the X and Z reports print, taken from the pro tills and Vitec's.

	Each figure here is one the user's own Vitec report shows, or one Toast,
	Foodics and Lightspeed put on theirs and Vitec's lacks.
	"""

	def test_a_method_says_what_it_took_and_what_it_gave_back(self):
		"""The net alone cannot tell a quiet shift from a busy one with a refund in it."""
		entry = self._opened("multi")
		order = self._sold_by(frappe.session.user)
		refund = self._refund_one(order)

		cash = next(row for row in service.summarise_till(entry)["by_method"] if row["method"] == CASH)

		self.assertAlmostEqual(cash["taken"], flt(order.total_amount), places=2)
		self.assertAlmostEqual(cash["refunded"], refund["refund_amount"], places=2)
		self.assertAlmostEqual(cash["sales"], cash["taken"] - cash["refunded"], places=2)

	def test_the_tax_table_adds_up_to_what_was_charged(self):
		entry = self._opened("multi")
		order = self._sold_by(frappe.session.user)

		taxes = service.summarise_till(entry)["taxes"]

		self.assertTrue(taxes)
		gross = sum(row["gross"] for row in taxes)
		self.assertAlmostEqual(
			gross, flt(frappe.db.get_value("Sales Invoice", order.sales_invoice, "grand_total")), places=2
		)
		self.assertAlmostEqual(sum(row["net"] + row["tax"] for row in taxes), gross, places=2)

	def test_a_voided_line_is_counted_by_what_it_was_worth(self):
		entry = self._opened("multi")
		order = self._sold_by(frappe.session.user)
		before = service.summarise_till(entry)
		line = order.items[0]
		frappe.db.set_value("Restaurant Order Item", line.name, "status", "void", update_modified=False)

		after = service.summarise_till(entry)

		self.assertEqual(after["voids"] - before["voids"], 1)
		self.assertAlmostEqual(after["void_amount"] - before["void_amount"], flt(line.amount), places=2)

	def test_an_open_bill_is_counted_by_its_amount_in_the_day(self):
		outcome = service.open_till(pos_profile=self.profile)
		before = service.summarise(outcome["shift"])["open_amount"]
		order = self._order()
		orders.add_item(order, item=ITEM, qty=1)
		order.reload()

		after = service.summarise(outcome["shift"])["open_amount"]

		self.assertAlmostEqual(after - before, flt(order.total_amount), places=2)

	def test_the_day_lists_each_drawer_it_counted_and_the_difference(self):
		# **No write to the branch here.** Closing a drawer commits, so a setting
		# written before it outlived the test: this test's first version left the
		# test site's branch personal and counting, and the payment and refund
		# suites run next found no drawer to sell into. The count is asked for
		# through the profile the close reads instead.
		entry = service.open_till(pos_profile=self.profile, opening_floats={CASH: 100})["entry"]
		self._sold_by(frappe.session.user)
		expected = service.summarise_till(entry)["till_expected"]
		read_profile = service._profile

		def counting(pos_profile):
			profile = read_profile(pos_profile)
			profile.settlement_required = 1
			return profile

		with patch.object(service, "_profile", side_effect=counting):
			service.close_till(opening_entry=entry, counted={CASH: expected + 5}, variance_reason="RPOS test")
		day = frappe.db.get_value("POS Opening Entry", entry, "rpos_restaurant_shift")

		till = next(row for row in service.summarise(day)["tills"] if row["user"] == frappe.session.user)
		self.assertAlmostEqual(till["difference"], 5, places=2)
		self.assertAlmostEqual(till["counted"] - till["expected"], 5, places=2)


class TestOpening(ShiftTestBase):
	def test_a_terminal_with_nothing_open_says_so(self):
		frappe.db.set_value("POS Profile", self.profile, "restaurant_shift", None)

		state = service.shift_state(self.profile)

		self.assertFalse(state["day"]["open"])
		self.assertFalse(state["till"]["open"])

	def test_taking_the_drawer_opens_the_day_too(self):
		"""One button in the morning, not two (FR-8.1)."""
		outcome = service.open_till(pos_profile=self.profile)

		state = service.shift_state(self.profile)
		self.assertTrue(state["day"]["open"])
		self.assertTrue(state["till"]["open"])
		self.assertEqual(state["day"]["shift"], outcome["shift"])

	def test_the_terminal_is_pointed_at_the_day(self):
		"""BR-044 — the terminal cannot sell until this is true."""
		outcome = service.open_till(pos_profile=self.profile)

		self.assertEqual(
			frappe.db.get_value("POS Profile", self.profile, "restaurant_shift"), outcome["shift"]
		)

	def test_the_till_records_which_day_it_belongs_to(self):
		"""D-047 — ERPNext has no business day, so we give its entry one."""
		outcome = service.open_till(pos_profile=self.profile)

		self.assertEqual(
			frappe.db.get_value("POS Opening Entry", outcome["entry"], "rpos_restaurant_shift"),
			outcome["shift"],
		)

	def test_a_second_day_is_never_opened(self):
		"""Two days would split one day of takings across two reports."""
		first = service.open_day(pos_profile=self.profile)

		again = service.open_day(pos_profile=self.profile)

		self.assertTrue(again["joined"])
		self.assertEqual(again["shift"], first["shift"])

	def test_a_single_drawer_branch_shares_it(self):
		"""BR-041 — one drawer, and the next cashier finds it rather than a lock."""
		frappe.db.set_value("Branch", BRANCH, "shift_type", "single")
		first = service.open_till(pos_profile=self.profile)

		again = service.open_till(pos_profile=self.profile)

		self.assertTrue(again["joined"])
		self.assertEqual(again["entry"], first["entry"])

	def test_a_credit_float_is_refused_quietly(self):
		"""A float on a platform method would inflate a drawer that holds nothing."""
		self.assertEqual(service._clean_floats({"Cash": 200, "Jahez": 500}), {"Cash": 200.0})

	def test_an_unknown_method_is_refused_loudly(self):
		with self.assertRaises(frappe.ValidationError):
			service._clean_floats({"Nonesuch": 100})


class TestASharedDrawerCountsEveryone(ShiftTestBase):
	"""`BR-041`, `D-218` — in a `single` branch the drawer is the terminal's, not a person's.

	The next cashier joins the one already open — which is how Vitec works and
	how the user's customers cover a cashier gone to the store for ten minutes.
	The count read only the sales **under the opener's name**, so everything the
	one covering took was in the drawer and missing from what it was expected to
	hold: a shortage nobody could explain, on the branch set up to share.
	"""

	def test_a_sale_by_whoever_joined_counts_in_the_shared_drawer(self):
		entry = self._opened("single")
		before = service.summarise_till(entry)["till_expected"]

		order = self._sold_by(SECOND_CASHIER)

		self.assertAlmostEqual(
			service.summarise_till(entry)["till_expected"] - before, flt(order.total_amount), places=2
		)

	def test_and_so_does_a_refund_they_paid_out_of_it(self):
		entry = self._opened("single")
		order = self._sold_by(SECOND_CASHIER)
		row = frappe.db.get_value("Sales Invoice Item", {"parent": order.sales_invoice}, "name")
		before = service.summarise_till(entry)

		refund = returns.create_return(order, items=[{"row": row, "qty": 1}], reason_code="goods_returned")
		frappe.db.set_value(
			"Sales Invoice", refund["credit_note"], "owner", SECOND_CASHIER, update_modified=False
		)
		after = service.summarise_till(entry)

		self.assertAlmostEqual(after["returns"] - before["returns"], refund["refund_amount"], places=2)

	def test_the_report_says_what_each_of_them_took(self):
		"""FR-8.3 — counted once for everybody, and still traced to a name, as Vitec's report does."""
		entry = self._opened("single")
		order = self._sold_by(SECOND_CASHIER)

		row = next(
			row for row in service.summarise_till(entry)["by_cashier"] if row["user"] == SECOND_CASHIER
		)

		self.assertEqual(row["count"], 1)
		self.assertAlmostEqual(row["sales"], flt(order.total_amount), places=2)

	def test_a_second_personal_drawer_is_refused_and_the_first_is_named(self):
		"""`D-218` — the user opened a drawer at one branch while theirs stood open at another."""
		frappe.db.set_value("Branch", BRANCH, "shift_type", "multi")
		elsewhere = frappe._dict(
			name="POS-OPE-ELSEWHERE", pos_profile="RPOS Far Terminal", period_start_date=now_datetime()
		)

		with (
			patch.object(service, "held_till", return_value=elsewhere),
			self.assertRaisesRegex(frappe.ValidationError, "RPOS Far Terminal"),
		):
			service.open_till(pos_profile=self.profile)

	def test_a_personal_drawer_still_counts_only_its_own_cashier(self):
		"""`multi` — each cashier's drawer is theirs, and somebody else's sale is not in it."""
		entry = self._opened("multi")
		before = service.summarise_till(entry)["till_expected"]

		self._sold_by(SECOND_CASHIER)

		self.assertAlmostEqual(service.summarise_till(entry)["till_expected"], before, places=2)


class TestTheDrawer(ShiftTestBase):
	def test_the_opening_float_is_expected_in_it(self):
		outcome = service.open_till(pos_profile=self.profile, opening_floats={"Cash": 200})

		report = service.summarise_till(outcome["entry"])

		cash = next(row for row in report["by_method"] if row["method"] == "Cash")
		self.assertEqual(cash["opening"], 200.0)
		self.assertEqual(cash["expected"], 200.0)
		self.assertEqual(report["till_expected"], 200.0)

	def test_closing_it_writes_an_erpnext_closing_entry(self):
		"""D-047 — the count belongs in ERPNext own POS reconciliation."""
		outcome = service.open_till(pos_profile=self.profile, opening_floats={"Cash": 200})

		closed = service.close_till(opening_entry=outcome["entry"])

		self.assertTrue(closed["closing_entry"])
		self.assertEqual(frappe.db.get_value("POS Closing Entry", closed["closing_entry"], "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("POS Opening Entry", outcome["entry"], "status"), "Closed")

	def test_a_closed_drawer_cannot_be_closed_again(self):
		outcome = service.open_till(pos_profile=self.profile)
		service.close_till(opening_entry=outcome["entry"])

		with self.assertRaises(frappe.ValidationError):
			service.close_till(opening_entry=outcome["entry"])

	def test_closing_the_drawer_leaves_the_day_open(self):
		"""The whole point of two levels: the next cashier keeps selling."""
		outcome = service.open_till(pos_profile=self.profile)

		service.close_till(opening_entry=outcome["entry"])

		state = service.shift_state(self.profile)
		self.assertTrue(state["day"]["open"])
		self.assertFalse(state["till"]["open"])

	def test_a_difference_demands_a_reason(self):
		frappe.db.set_value("Branch", BRANCH, "settlement_required", 1)
		outcome = service.open_till(pos_profile=self.profile, opening_floats={"Cash": 200})

		with self.assertRaises(frappe.ValidationError):
			service.close_till(opening_entry=outcome["entry"], counted={"Cash": 190})

	def test_the_difference_is_recorded(self):
		frappe.db.set_value("Branch", BRANCH, "settlement_required", 1)
		outcome = service.open_till(pos_profile=self.profile, opening_floats={"Cash": 200})

		closed = service.close_till(
			opening_entry=outcome["entry"], counted={"Cash": 190}, variance_reason="نقص في الصرافة"
		)

		self.assertEqual(closed["settlement"]["variance"], -10.0)
		row = frappe.get_all(
			"POS Closing Entry Detail",
			filters={"parent": closed["closing_entry"], "mode_of_payment": "Cash"},
			fields=["expected_amount", "closing_amount", "difference"],
		)[0]
		self.assertEqual(row.expected_amount, 200.0)
		self.assertEqual(row.closing_amount, 190.0)
		self.assertEqual(row.difference, -10.0)
		self.assertEqual(
			frappe.db.get_value("POS Closing Entry", closed["closing_entry"], "rpos_variance_reason"),
			"نقص في الصرافة",
		)

	def test_without_settlement_there_is_nothing_to_explain(self):
		"""BR-042 — a shop that does not count has no difference to account for."""
		frappe.db.set_value("Branch", BRANCH, "settlement_required", 0)
		outcome = service.open_till(pos_profile=self.profile, opening_floats={"Cash": 200})

		closed = service.close_till(opening_entry=outcome["entry"])

		self.assertFalse(closed["settlement"]["settlement_required"])
		self.assertEqual(closed["settlement"]["variance"], 0.0)


class TestEndOfDay(ShiftTestBase):
	def test_an_open_order_blocks_it(self):
		outcome = service.open_till(pos_profile=self.profile)
		self._order()

		with self.assertRaises(frappe.ValidationError):
			service.close_day(shift_name=outcome["shift"])

	def test_a_branch_may_let_bills_run_past_midnight(self):
		"""D-105 — the restaurant decides what an open bill means at closing.

		A tab that runs late, or a numbered bill emptied and reused for the next
		customer, is an ordinary evening in some restaurants. In others a bill
		still open at the end of the night is an incident. The setting is the
		difference, and neither answer is wrong.
		"""
		frappe.db.set_value("Branch", BRANCH, "close_open_orders_with_day", 0)
		outcome = service.open_till(pos_profile=self.profile)
		order = self._order()

		service.close_day(shift_name=outcome["shift"])

		self.assertEqual(frappe.db.get_value("Restaurant Shift", outcome["shift"], "status"), "closed")
		self.assertNotIn(
			frappe.db.get_value("Restaurant Order", order.name, "status"),
			("closed", "cancelled"),
			"the bill carries over rather than being settled by the day ending",
		)

	def test_a_carried_over_bill_still_takes_items_tomorrow(self):
		"""The rule this replaced refused, and refusing was wrong (`D-105`).

		`assert_mutable` still asks for an open till, which is what closed the
		original hole — paying a held draft with no shift open. What it does not
		ask any more is which day the bill was opened on.
		"""
		from restaurant_pos.tests.test_order import ITEM
		from restaurant_pos.utils import order as orders

		frappe.db.set_value("Branch", BRANCH, "close_open_orders_with_day", 0)
		yesterday = service.open_till(pos_profile=self.profile)
		order = self._order()
		service.close_day(shift_name=yesterday["shift"])

		# A new day, a new drawer — the cashier is at work and the bill is on the
		# floor in front of them.
		service.open_till(pos_profile=self.profile)
		order.reload()

		orders.add_item(order, item=ITEM, qty=1)

		self.assertTrue(order.items)

	def test_a_manager_may_close_over_it(self):
		outcome = service.open_till(pos_profile=self.profile)
		self._order()

		service.close_day(shift_name=outcome["shift"], force=True)

		self.assertEqual(frappe.db.get_value("Restaurant Shift", outcome["shift"], "status"), "closed")

	def test_the_report_says_which_rule_this_branch_keeps(self):
		"""So the screen can name the reason instead of drawing a dead button.

		`D-074` — a control that refuses and explains nothing is the report a
		cashier cannot act on, and the till has three different things to say
		about an open bill here depending on the branch and the reader.
		"""
		outcome = service.open_till(pos_profile=self.profile)

		self.assertTrue(service.summarise(outcome["shift"])["must_finish_orders"])

		frappe.db.set_value("Branch", BRANCH, "close_open_orders_with_day", 0)
		self.assertFalse(service.summarise(outcome["shift"])["must_finish_orders"])

	def test_it_sweeps_up_a_drawer_left_open(self):
		"""The cashier who went home is not coming back to count it."""
		outcome = service.open_till(pos_profile=self.profile, opening_floats={"Cash": 200})

		closed = service.close_day(shift_name=outcome["shift"], force=True)

		self.assertEqual(len(closed["closed_tills"]), 1)
		self.assertEqual(frappe.db.get_value("POS Opening Entry", outcome["entry"], "status"), "Closed")

	def test_it_stops_the_terminal_selling(self):
		"""BR-044 — a till pointed at a closed day must refuse the next order."""
		outcome = service.open_till(pos_profile=self.profile)

		service.close_day(shift_name=outcome["shift"], force=True)

		self.assertIsNone(frappe.db.get_value("POS Profile", self.profile, "restaurant_shift"))

	def test_a_closed_day_cannot_be_closed_again(self):
		outcome = service.open_till(pos_profile=self.profile)
		service.close_day(shift_name=outcome["shift"], force=True)

		with self.assertRaises(frappe.ValidationError):
			service.close_day(shift_name=outcome["shift"], force=True)


class TestOneBranchCannotReadAnother(ShiftTestBase):
	"""`summarise_till` checked no branch while `summarise` beside it did.

	Found by `test_api_surface`, which walks every whitelisted endpoint looking
	for a guard. A cashier restricted to one branch could name another branch's
	opening entry and read its takings — and `get_till_summary` opens the cash
	drawer as it answers (`D-093`), so it popped that branch's drawer too.
	"""

	CASHIER = "rpos_other_branch@example.com"
	#: A real Branch, because `User Permission` validates the link — restricting
	#: someone to a branch that does not exist is refused before the test starts.
	OTHER = "_RPOS Other Branch"

	def setUp(self):
		super().setUp()
		if not frappe.db.exists("Branch", self.OTHER):
			# Company, warehouse and cost centre are mandatory on a Branch here
			# (`setup/install.py`), so it is copied from the real one rather
			# than invented — the test is about the branch check, not about
			# what a second branch would be configured with.
			like = frappe.db.get_value(
				"Branch", BRANCH, ["company", "default_warehouse", "default_cost_center"], as_dict=True
			)
			frappe.get_doc({"doctype": "Branch", "branch": self.OTHER, **like}).insert(
				ignore_permissions=True
			)
		if not frappe.db.exists("User", self.CASHIER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": self.CASHIER,
					"first_name": "RPOS Other Branch",
					"send_welcome_email": 0,
					"roles": [{"role": "POS Cashier"}],
				}
			).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in frappe.get_all(
			"User Permission", filters={"user": self.CASHIER, "allow": "Branch"}, pluck="name"
		):
			frappe.delete_doc("User Permission", name, force=True, ignore_permissions=True)
		super().tearDown()

	def test_a_till_summary_is_refused_across_branches(self):
		entry = service.open_till(pos_profile=self.profile)["entry"]

		# Restricted to a branch that is not the one holding this drawer.
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": self.CASHIER,
				"allow": "Branch",
				"for_value": self.OTHER,
			}
		).insert(ignore_permissions=True)

		frappe.set_user(self.CASHIER)
		with self.assertRaises(frappe.PermissionError):
			service.summarise_till(entry)


class TheDayDoesNotCloseOverBillsOnATickBox(ShiftTestBase):
	"""`D-156` — the branch setting was a suggestion, and this is why.

	`D-105` gave the restaurant the rule: with `close_open_orders_with_day` on,
	**the day does not end while a bill is open**. The rule was enforced — and
	then handed away. `close_day` took a `force` flag that nothing guarded, the
	close-day screen drew *"close the day anyway"* beside the count whenever a
	bill was open, and `can_close_shift` ships **on** for a plain cashier. So
	the branch could set the rule and any cashier could tick past it.

	A day closed over bills nobody meant to carry cannot be undone. The way past
	is a right now, and these run **as the users who do or do not hold it** —
	Administrator passes every permission check on the first line
	(`06_git_testing_rules.md`), so asserting as Administrator would prove that
	the flag still exists and nothing more.
	"""

	CASHIER = "rpos_day_cashier@example.com"
	MANAGER = "rpos_day_manager@example.com"

	def setUp(self):
		super().setUp()
		from restaurant_pos.setup.defaults import PERMISSION_SETS, create_default_data

		if not frappe.db.exists("POS Permission Set", "POS Manager"):
			create_default_data()

		# The shipped answer is what is under test, not whatever an earlier test
		# left on the row (`D-013` — defaults are never re-applied after install).
		for role in ("POS Cashier", "POS Manager"):
			frappe.db.set_value(
				"POS Permission Set",
				role,
				"can_close_day_with_open_orders",
				PERMISSION_SETS[role]["can_close_day_with_open_orders"],
			)

		self._user(self.CASHIER, "POS Cashier", "RPOS Day Cashier")
		self._user(self.MANAGER, "POS Manager", "RPOS Day Manager")
		frappe.local.rpos_permission_cache = {}

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.rpos_permission_cache = {}
		super().tearDown()

	def _user(self, email: str, role: str, name: str) -> None:
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": name,
					"send_welcome_email": 0,
					"roles": [{"role": role}],
				}
			).insert(ignore_permissions=True)

	def _as(self, user: str) -> None:
		frappe.set_user(user)
		frappe.local.rpos_permission_cache = {}

	def _a_day_with_a_bill_left_open(self, user: str) -> str:
		"""Opened by this user, so `can_close_others_shift` never enters into it.

		Closing somebody else's day is a different right (`BR-045`), and a test
		that tripped over it would be reporting the wrong refusal.
		"""
		self._as(user)
		outcome = service.open_till(pos_profile=self.profile)
		self._order()
		return outcome["shift"]

	def test_a_cashier_cannot_tick_past_it(self):
		"""The defect, exactly: `can_close_shift` is on for every cashier."""
		day = self._a_day_with_a_bill_left_open(self.CASHIER)

		with self.assertRaises(frappe.PermissionError):
			service.close_day(shift_name=day, force=True)

		self.assertEqual(frappe.db.get_value("Restaurant Shift", day, "status"), "open")

	def test_and_is_still_refused_plainly_without_the_flag(self):
		"""The ordinary answer stays a validation error, not a permission one.

		The cashier has not done anything they may not do — there are bills to
		settle, and the message has to be about the bills.
		"""
		day = self._a_day_with_a_bill_left_open(self.CASHIER)

		with self.assertRaises(frappe.ValidationError):
			service.close_day(shift_name=day)

	def test_a_manager_may(self):
		day = self._a_day_with_a_bill_left_open(self.MANAGER)

		service.close_day(shift_name=day, force=True)

		self.assertEqual(frappe.db.get_value("Restaurant Shift", day, "status"), "closed")

	def test_where_the_branch_allows_it_nobody_needs_the_right(self):
		"""`D-105` — with the setting off there is nothing to be let past.

		The cashier closes the day and the bills carry over, which is the whole
		point of the setting. Asking for a manager here would make the setting
		mean the opposite of what it says.
		"""
		frappe.db.set_value("Branch", BRANCH, "close_open_orders_with_day", 0)
		day = self._a_day_with_a_bill_left_open(self.CASHIER)

		service.close_day(shift_name=day)

		self.assertEqual(frappe.db.get_value("Restaurant Shift", day, "status"), "closed")


class TheCashierHoldingTheDrawerCanHandItBack(ShiftTestBase):
	"""`D-157` — and none of them could.

	`close_till` submits a `POS Closing Entry`, and ERPNext's `on_submit` reaches
	`update_opening_entry`, which loads the `POS Opening Entry` fresh and **saves
	it as whoever is standing there**. No POS role has desk rights on an
	accounting document — that is deliberate (`08_Security.md` §1) — so every
	real cashier died there on a bare `PermissionError`: no message, no number,
	and the drawer still open. And with it every end of day, because closing the
	day sweeps the drawers up first.

	It went unseen for the same reason `D-144` did: **every test in this module
	ran as Administrator**, who passes every permission check on the first line.
	So these run as a cashier, and they are the only ones here that do.
	"""

	CASHIER = "rpos_drawer_cashier@example.com"

	def setUp(self):
		super().setUp()
		from restaurant_pos.tests.test_order import _make_cashier

		_make_cashier()
		if not frappe.db.exists("User", self.CASHIER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": self.CASHIER,
					"first_name": "RPOS Drawer Cashier",
					"send_welcome_email": 0,
					"roles": [{"role": "POS Cashier"}],
				}
			).insert(ignore_permissions=True)

		frappe.set_user(self.CASHIER)
		frappe.local.rpos_permission_cache = {}

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.rpos_permission_cache = {}
		super().tearDown()

	def test_a_cashier_can_close_their_own_drawer(self):
		outcome = service.open_till(pos_profile=self.profile, opening_floats={"Cash": 200})

		closed = service.close_till(opening_entry=outcome["entry"])

		self.assertEqual(frappe.db.get_value("POS Opening Entry", outcome["entry"], "status"), "Closed")
		self.assertEqual(frappe.db.get_value("POS Closing Entry", closed["closing_entry"], "docstatus"), 1)

	def test_the_count_is_filed_under_the_cashier_who_made_it(self):
		"""The rights are borrowed for the submit alone (`D-144`, `D-157`).

		If the whole call ran as Administrator the books would say Administrator
		counted the drawer, which is the one thing a reconciliation must not say.
		"""
		outcome = service.open_till(pos_profile=self.profile, opening_floats={"Cash": 200})

		closed = service.close_till(opening_entry=outcome["entry"])

		self.assertEqual(
			frappe.db.get_value("POS Closing Entry", closed["closing_entry"], "owner"), self.CASHIER
		)
		# And the session is given straight back.
		self.assertEqual(frappe.session.user, self.CASHIER)

	def test_a_cashier_can_end_the_day(self):
		"""The sweep is the part that reaches ERPNext, so it is the part that broke."""
		outcome = service.open_till(pos_profile=self.profile, opening_floats={"Cash": 200})

		service.close_day(shift_name=outcome["shift"])

		self.assertEqual(frappe.db.get_value("Restaurant Shift", outcome["shift"], "status"), "closed")
		self.assertEqual(frappe.db.get_value("POS Opening Entry", outcome["entry"], "status"), "Closed")


class CarryingTooManyIsSaidNotRefused(ShiftTestBase):
	"""`D-158` — the pile gets mentioned; the day still closes.

	`D-105` lets a branch carry bills past midnight, and nothing else ever
	forces one closed — so *"carries over"* becomes *"for ever"*: three bills
	abandoned a night is a thousand in a year. The floor is unbounded by date on
	purpose (`D-146`), so the till reads all of them on every refresh. Measured
	on the test site: 1,155 open bills draw in 0.62s, 3,155 in 4.31s, 5,155 in
	8.35s.

	**A ceiling stood here for an hour and it was the wrong shape.** The user
	rejected it and was right: ending the business day is an accounting act and
	a long list is a technical complaint, so refusing the first for the second
	would strand a manager at two in the morning over something recoverable at
	any time. These hold the shape the answer settled into — **the number is
	said, to the person who can act on it, and nothing is refused.**
	"""

	def _carrying(self, warn_at: int, bills: int) -> str:
		frappe.db.set_value(
			"Branch", BRANCH, {"close_open_orders_with_day": 0, "carried_orders_warning_at": warn_at}
		)
		outcome = service.open_till(pos_profile=self.profile)
		for _ in range(bills):
			self._order()
		return outcome["shift"]

	def test_the_day_closes_however_many_are_carried(self):
		"""The whole point: this never stands between a manager and their day."""
		day = self._carrying(warn_at=2, bills=5)

		service.close_day(shift_name=day)

		self.assertEqual(frappe.db.get_value("Restaurant Shift", day, "status"), "closed")

	def test_over_the_number_the_report_says_so(self):
		day = self._carrying(warn_at=2, bills=5)

		report = service.summarise(day)

		self.assertTrue(report["carrying_too_many"])
		self.assertEqual(report["carry_over_warning_at"], 2)
		# And it is a warning, not the thing that refuses.
		self.assertFalse(report["blocked_by_open_orders"])

	def test_under_it_nothing_is_said(self):
		day = self._carrying(warn_at=5, bills=2)

		self.assertFalse(service.summarise(day)["carrying_too_many"])

	def test_the_number_itself_is_not_over_it(self):
		day = self._carrying(warn_at=3, bills=3)

		self.assertFalse(service.summarise(day)["carrying_too_many"])

	def test_zero_means_never_mention_it(self):
		"""A branch that really does want them to pile up is not nagged."""
		day = self._carrying(warn_at=0, bills=5)

		self.assertFalse(service.summarise(day)["carrying_too_many"])

	def test_a_branch_that_finishes_its_orders_is_never_warned(self):
		"""There is nothing to carry, so there is nothing to say about it — and
		the refusal that *does* apply is `D-105`'s, not this."""
		frappe.db.set_value(
			"Branch", BRANCH, {"close_open_orders_with_day": 1, "carried_orders_warning_at": 1}
		)
		outcome = service.open_till(pos_profile=self.profile)
		self._order()
		self._order()

		report = service.summarise(outcome["shift"])

		self.assertFalse(report["carrying_too_many"])
		self.assertTrue(report["blocked_by_open_orders"])

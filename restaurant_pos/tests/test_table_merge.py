# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""One party across two tables (`BR-063`, `FR-5.4`).

**The industry calls two different things "merge", and confusing them is how a
floor plan starts lying.** Toast merges *checks* — two bills become one. Square
merges *tables* — two tables become one unit on the plan and their bills are
left alone. We had the first (`BR-067`) and not the second, and the gap showed
up as a defect rather than a missing feature:

> Guests at table 5 and guests at table 6 ask to pay together. The cashier
> merges the bills. **Table 6 goes green on the floor plan while they are
> still sitting at it.**

`merge_orders` cancelled the emptied bill and released its table, which is right
when a bill is merged into another on the *same* table and wrong the moment the
two are in different places. And the join screen offers every open bill of the
type, not just the ones on one table, so it was reachable from the till.

Both features need the same one thing — **an order that can hold more than one
table** — which is why they are built together here.

Refs: BR-063, BR-066, FR-5.4, D-058, D-160
"""

import frappe

from restaurant_pos.tests.test_order import ITEM, OrderTestBase, free_table
from restaurant_pos.utils import order as service


class TwoTablesOnePartyBase(OrderTestBase):
	"""Two real tables in this terminal's section, empty before each test."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.tables = frappe.get_all(
			"Restaurant Table",
			filters={"section": cls.section, "is_active": 1},
			order_by="name asc",
			limit=2,
			pluck="name",
		)

	def setUp(self):
		if len(self.tables) < 2:
			self.skipTest("this section has fewer than two tables")

		for table in self.tables:
			free_table(table)

	def tearDown(self):
		frappe.set_user("Administrator")
		for table in self.tables:
			free_table(table)

	def _seat(self, table: str):
		"""A dine-in bill with a line on it, at this table."""
		order = self._order(order_type=self.dine_in, table=table, cover_count=2)
		service.add_item(order, item=ITEM, qty=1)
		order.reload()
		return order

	# ------------------------------------------------------------------ #

	def _status(self, table: str) -> str:
		return frappe.db.get_value("Restaurant Table", table, "status")


class TheFloorPlanTellsTheTruthAboutBothTables(TwoTablesOnePartyBase):
	"""The defect this work started from.

	A floor plan exists to say where people are. A table drawn free while a
	party is eating at it sends the next guests to a taken seat — and it is the
	host who finds out, in front of them.
	"""

	def test_merging_the_bills_leaves_both_tables_occupied(self):
		first, second = self.tables
		into = self._seat(first)
		other = self._seat(second)

		service.merge_orders(other, into)

		self.assertEqual(self._status(first), "occupied")
		self.assertEqual(
			self._status(second),
			"occupied",
			"the guests are still sitting at the table their bill moved off",
		)

	# ------------------------------------------------------------------ #

	def test_the_bill_holds_both_tables_afterwards(self):
		"""Because that is what keeps them occupied — nothing else is tracking it."""
		first, second = self.tables
		into = self._seat(first)
		other = self._seat(second)

		service.merge_orders(other, into)
		into.reload()

		self.assertEqual(service.tables_of(into), [first, second])

	def test_paying_it_frees_both(self):
		"""`BR-063` — the merge is reversed when the order closes, and by it.

		`cleaning`, not `available`: a paid table is not free until somebody has
		wiped it (`BR-061`, `FR-2.7g`). What matters here is that **both** leave
		`occupied`, by the same path and at the same moment.
		"""
		from restaurant_pos.tests.test_payment import CASH, _ensure_fiscal_year
		from restaurant_pos.utils import payment

		_ensure_fiscal_year()
		first, second = self.tables
		into = self._seat(first)
		service.merge_orders(self._seat(second), into)
		into.reload()

		payment.process_payment(into, payments=[{"method": CASH, "amount": into.total_amount}])

		self.assertEqual(self._status(first), "cleaning")
		self.assertEqual(self._status(second), "cleaning")


class JoiningAFreeTableToABill(TwoTablesOnePartyBase):
	"""`BR-063` the other way round: one party, one bill, from the start.

	A group of ten takes tables 5 and 6 and orders together. There is nothing to
	merge — there is one bill — and the till still has to say both tables are
	taken.
	"""

	def test_the_bill_takes_the_second_table(self):
		first, second = self.tables
		order = self._seat(first)

		outcome = service.merge_tables(order, tables=[second])

		self.assertEqual(outcome["joined"], [second])
		self.assertEqual(self._status(second), "occupied")
		self.assertEqual(
			frappe.db.get_value("Restaurant Table", second, "current_order"),
			order.name,
			"tapping the joined table has to reach the bill it belongs to",
		)

	def test_both_tables_reach_one_bill(self):
		"""There is one party, so there is one bill — not two to reconcile."""
		first, second = self.tables
		order = self._seat(first)

		service.merge_tables(order, tables=[second])
		order.reload()

		self.assertEqual(service.tables_of(order), [first, second])
		self.assertEqual(service.open_orders_on(second), [order.name])

	def test_a_table_that_already_has_a_bill_is_refused(self):
		"""And the refusal names the thing the cashier can actually do.

		Joining it would strand that bill on a table nothing is drawing any
		more. Putting the two bills together is a different act with a different
		permission — so the message says so rather than "table 6 is occupied",
		which is true and useless.
		"""
		first, second = self.tables
		order = self._seat(first)
		self._seat(second)

		with self.assertRaises(frappe.ValidationError) as refused:
			service.merge_tables(order, tables=[second])

		self.assertIn(second, str(refused.exception))

	def test_joining_the_table_it_is_already_on_is_refused(self):
		"""Rather than silently doing nothing and reporting success."""
		first, _second = self.tables
		order = self._seat(first)

		with self.assertRaises(frappe.ValidationError):
			service.merge_tables(order, tables=[first])

	def test_a_bill_with_no_table_has_nothing_to_join_to(self):
		"""A takeaway is not a party spread across the room."""
		order = self._order()

		with self.assertRaises(frappe.ValidationError):
			service.merge_tables(order, tables=[self.tables[1]])

	def test_cancelling_frees_every_table(self):
		"""`BR-063` — the join is reversed by the bill ending, however it ends."""
		first, second = self.tables
		order = self._seat(first)
		service.merge_tables(order, tables=[second])
		order.reload()

		service.cancel_order(order, reason="RPOS test")

		self.assertEqual(self._status(first), "available")
		self.assertEqual(self._status(second), "available")


class TheRightThatFinallyDoesSomething(TwoTablesOnePartyBase):
	"""`can_merge_tables` was shipped in every permission set and **read by
	nothing** — off for a cashier, on for a manager, and granting neither of them
	anything. A permission that grants nothing is worse than a missing one: it
	tells whoever configures the branch that a decision has been made.

	Run as the users themselves, because `Administrator` passes every permission
	check on its first line and would prove only that the flag still exists
	(`06_git_testing_rules.md`, `D-144`).
	"""

	CASHIER = "rpos_merge_cashier@example.com"
	MANAGER = "rpos_merge_manager@example.com"

	def setUp(self):
		super().setUp()
		from restaurant_pos.setup.defaults import PERMISSION_SETS, create_default_data

		if not frappe.db.exists("POS Permission Set", "POS Manager"):
			create_default_data()

		# The shipped answer is what is under test, not whatever an earlier test
		# left on the row (`D-013` — defaults are never re-applied after install).
		for role in ("POS Cashier", "POS Manager"):
			frappe.db.set_value(
				"POS Permission Set", role, "can_merge_tables", PERMISSION_SETS[role]["can_merge_tables"]
			)

		self._user(self.CASHIER, "POS Cashier", "RPOS Merge Cashier")
		self._user(self.MANAGER, "POS Manager", "RPOS Merge Manager")
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

	def test_a_cashier_may_not(self):
		first, second = self.tables
		order = self._seat(first)

		self._as(self.CASHIER)
		with self.assertRaises(frappe.PermissionError):
			service.merge_tables(order, tables=[second])

		self.assertEqual(self._status(second), "available", "and nothing moved")

	def test_a_manager_may(self):
		first, second = self.tables
		order = self._seat(first)

		self._as(self.MANAGER)
		service.merge_tables(order, tables=[second])

		self.assertEqual(self._status(second), "occupied")


class TheJoinedTableCarriesItsPartysBill(TwoTablesOnePartyBase):
	"""The tap that did nothing (`D-183`).

	Occupancy was right — the joined table went red and stayed red. What it did
	not have was **the bill**: `_annotate_orders` matched `Restaurant Order.table`
	alone, so the second table of a party carried an empty `orders` list. On the
	floor plan that reads as *"4 seats"*, the very line an empty table shows, and
	the tap fell through both branches of `onTable` — open the bill when there is
	one, seat when the table is free — and returned.

	A waiter tapping a table with people at it got nothing at all. Silence is
	the worst report a till can give (`D-074`), and this one was on the busiest
	screen in the building.

	Drawing the two as a merged unit is deferred by the user (`D-183`); this is
	not that. It is the bill being reachable from the table it is eaten at.
	"""

	def _plan(self) -> dict:
		from restaurant_pos.api.table import get_floor_plan

		return {row.name: row for row in get_floor_plan(self.section)["tables"]}

	def test_both_tables_carry_the_partys_bill(self):
		first, second = self.tables
		party = self._seat(first)
		service.merge_tables(party, tables=[second])

		plan = self._plan()

		self.assertEqual([row["name"] for row in plan[first].orders], [party.name])
		self.assertEqual(
			[row["name"] for row in plan[second].orders],
			[party.name],
			"the same party is sitting at it",
		)

	def test_the_joined_table_shows_the_bill_not_its_seat_count(self):
		"""The screen falls back to the seat count only when there is no bill —
		which is what made a table with people at it read as an empty one."""
		first, second = self.tables
		party = self._seat(first)
		service.merge_tables(party, tables=[second])

		joined = self._plan()[second].orders[0]

		self.assertEqual(joined["item_count"], 1)
		self.assertIsNotNone(joined["opened_at"])

	def test_an_unjoined_table_is_still_empty(self):
		"""The obvious other half: this must not hang bills on tables that have
		nobody at them."""
		first, second = self.tables
		self._seat(first)

		self.assertEqual(self._plan()[second].orders, [])

	def test_the_bill_lets_go_of_both_tables_when_it_closes(self):
		"""`BR-063` — the merge is reversed when the order closes, and the plan
		has to stop showing the party on either table."""
		first, second = self.tables
		party = self._seat(first)
		service.merge_tables(party, tables=[second])

		service.cancel_order(party, reason="RPOS test")

		plan = self._plan()
		self.assertEqual(plan[first].orders, [])
		self.assertEqual(plan[second].orders, [])


class APartySpreadAcrossTwoHalls(TwoTablesOnePartyBase):
	"""A bill joined onto a table in a **different** section (`D-183`).

	`merge_tables` scopes the join to the **branch**, not the section, so this is
	reachable: a party at a table on the terrace joined to one inside. The floor
	plan is asked for one section at a time, and a bill whose own table is in the
	other one has to be found by the table it was joined onto — not by the table
	it started at, which is nowhere in this query.

	This is the half of the fix nothing else covers. Reverting the lookup to the
	bill's own table left the same-section tests green, because there the bill is
	found by its own table and hung on the joined one from the same mapping.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		branch = frappe.db.get_value("Restaurant Section", cls.section, "branch")
		cls.other_section = frappe.db.get_value(
			"Restaurant Section", {"branch": branch, "name": ("!=", cls.section)}, "name"
		)
		if not cls.other_section:
			cls.other_section = (
				frappe.get_doc(
					{
						"doctype": "Restaurant Section",
						"title": "RPOS Test Terrace",
						"title_ar": "تراس الاختبار",
						"branch": branch,
						"section_type": "indoor",
					}
				)
				.insert(ignore_permissions=True)
				.name
			)

		cls.far_table = frappe.db.get_value(
			"Restaurant Table", {"section": cls.other_section, "is_active": 1}, "name"
		) or (
			frappe.get_doc(
				{
					"doctype": "Restaurant Table",
					"table_number": "RPOS-T99",
					"section": cls.other_section,
					"status": "available",
					"capacity": 4,
					"is_active": 1,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		frappe.db.commit()

	def setUp(self):
		super().setUp()
		free_table(self.far_table)

	def tearDown(self):
		free_table(self.far_table)
		super().tearDown()

	def test_the_far_table_carries_the_partys_bill(self):
		from restaurant_pos.api.table import get_floor_plan

		party = self._seat(self.tables[0])
		service.merge_tables(party, tables=[self.far_table])

		plan = {row.name: row for row in get_floor_plan(self.other_section)["tables"]}

		self.assertEqual(
			[row["name"] for row in plan[self.far_table].orders],
			[party.name],
			"its own table is in the other section, so only the join can find it",
		)

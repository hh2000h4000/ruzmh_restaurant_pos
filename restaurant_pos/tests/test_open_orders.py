# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The home screen's list of orders still on the floor.

Refs: 06 Screen 1, 07 §3, 04 §8
"""

import frappe
from frappe.utils import add_days, nowdate

from restaurant_pos.api import order as api
from restaurant_pos.tests.test_order import ITEM, OrderTestBase, _make_cashier
from restaurant_pos.tests.test_returns import REASON, ReturnTestBase
from restaurant_pos.utils import order as service
from restaurant_pos.utils import returns

#: A bill from before midnight — the case every history tab used to lose.
YESTERDAY = add_days(nowdate(), -1)


class TestOpenOrders(OrderTestBase):
	def _names(self):
		return {row["name"] for row in api.list_orders(self.profile)}

	def test_a_new_order_appears(self):
		order = self._order()
		self.assertIn(order.name, self._names())

	def test_a_cancelled_order_does_not(self):
		order = self._order()
		service.cancel_order(order, reason="RPOS test")
		self.assertNotIn(order.name, self._names())

	def test_a_card_carries_what_the_screen_draws(self):
		"""06 Screen 1 — type, when it opened, item count and status."""
		order = self._order()
		service.add_item(order, item=ITEM, qty=2)

		row = next(entry for entry in api.list_orders(self.profile) if entry["name"] == order.name)

		self.assertEqual(row["item_count"], 1)
		self.assertEqual(row["status"], order.status)
		self.assertIn("opened_at", row)
		self.assertTrue(row["order_type_title"])
		self.assertTrue(row["order_type_title_ar"])

	def test_a_voided_line_is_not_counted(self):
		order = self._order()
		service.add_item(order, item=ITEM, qty=1)
		service.void_item(order, item_idx=1, reason="RPOS test")

		row = next(entry for entry in api.list_orders(self.profile) if entry["name"] == order.name)
		self.assertEqual(row["item_count"], 0)

	def test_the_oldest_order_comes_first(self):
		"""The card that has waited longest is the one that needs attention."""
		first = self._order()
		second = self._order()

		listed = [row["name"] for row in api.list_orders(self.profile)]
		self.assertLess(listed.index(first.name), listed.index(second.name))

	def test_an_order_from_another_terminal_is_still_listed(self):
		"""Scoped to the branch, not the till.

		An order opened on a waiter's tablet has to be payable at the counter.
		Scoping by `pos_profile` would strand it.
		"""
		other = frappe.db.get_value(
			"POS Profile",
			{"name": ("!=", self.profile), "restaurant_section": self.section},
			"name",
		)
		if not other:
			self.skipTest("this site has only one POS Profile in the section")

		order = self._order()
		listed = {row["name"] for row in api.list_orders(other)}
		self.assertIn(order.name, listed)

	def test_a_card_names_the_cashier_who_opened_it(self):
		"""06 Screen 1 — whoever takes over a shift has to tell the tables apart."""
		order = self._order()

		row = next(entry for entry in api.list_orders(self.profile) if entry["name"] == order.name)
		self.assertTrue(row["cashier_name"])

	def test_listing_does_not_scale_with_the_number_of_orders(self):
		"""04 §8 — this list refreshes on every realtime event."""
		self._order()

		calls = 0
		real_get_all = frappe.get_all

		def counting(*args, **kwargs):
			nonlocal calls
			calls += 1
			return real_get_all(*args, **kwargs)

		frappe.get_all = counting
		try:
			api.list_orders(self.profile)
			baseline = calls
		finally:
			frappe.get_all = real_get_all

		for _ in range(5):
			service.add_item(self._order(), item=ITEM, qty=1)

		calls = 0
		frappe.get_all = counting
		try:
			api.list_orders(self.profile)
			after = calls
		finally:
			frappe.get_all = real_get_all

		self.assertEqual(after, baseline, "get_open_orders issued more queries for more orders")


class TestOrderViews(OrderTestBase):
	"""D-042 — the orders pane asks the server four different questions."""

	def test_an_unknown_view_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			api.list_orders(self.profile, view="everything")

	def test_a_draft_is_an_empty_bill(self):
		"""The whole content of the word (`D-122`).

		Asserted on the status rather than through a "drafts" view, which is
		gone: a tab filtering to bills with nothing on them showed what the card
		already says in its item count.
		"""
		draft = self._order()
		self.assertEqual(draft.status, "draft")

		service.add_item(draft, item=self.item, qty=1)
		self.assertEqual(draft.status, "active", "a bill with a line on it is not a draft")

	def test_history_holds_what_the_floor_does_not(self):
		order = self._order()
		service.add_item(order, item=self.item, qty=1)
		service.cancel_order(order, reason="test")

		self.assertNotIn(order.name, {row["name"] for row in api.list_orders(self.profile)})
		self.assertIn(order.name, {row["name"] for row in api.list_orders(self.profile, view="closed")})

	def test_all_is_both(self):
		open_order = self._order()
		closed = self._order()
		service.add_item(closed, item=self.item, qty=1)
		service.cancel_order(closed, reason="test")

		listed = {row["name"] for row in api.list_orders(self.profile, view="all")}

		self.assertIn(open_order.name, listed)
		self.assertIn(closed.name, listed)

	def test_history_is_newest_first(self):
		"""What a cashier wants from a closed order is the one they just closed."""
		rows = api.list_orders(self.profile, view="closed")
		if len(rows) < 2:
			self.skipTest("fewer than two closed orders today")

		# By when they **closed** (`D-146`) — the order the tab is sorted in.
		closed = [row["closed_at"] for row in rows]
		self.assertEqual(closed, sorted(closed, reverse=True))


class TheFloorIsSharedAndHistoryIsNot(OrderTestBase):
	"""`can_view_all_orders` scopes the day's history, not the floor (`D-121`).

	It used to scope both, and that was wrong twice over. It contradicted
	`list_orders`' own promise — that a bill left by the cashier who went on
	break is findable by the one taking over — and it did not even restrict:
	the floor plan lists a table's bills without asking who opened them, so the
	cashier tapped the table and opened the bill this list had hidden. A rule
	enforced on one screen and not the other is not a rule.

	Found by the user, on the demo site, looking at four red tables whose bills
	were nowhere in the open list.
	"""

	def setUp(self):
		self.cashier = _make_cashier()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.rpos_permission_cache = {}

	def _as_cashier(self):
		frappe.set_user(self.cashier)
		frappe.local.rpos_permission_cache = {}

	def test_an_open_bill_of_another_cashiers_is_visible(self):
		"""The one that matters at a shift change."""
		mine = self._order()  # opened as Administrator

		self._as_cashier()
		self.assertIn(mine.name, {row["name"] for row in api.list_orders(self.profile, "open")})

	def test_a_closed_bill_of_another_cashiers_is_not(self):
		theirs = self._order()
		service.add_item(theirs, item=ITEM, qty=1)
		theirs.save(ignore_permissions=True)
		theirs.reload()

		from restaurant_pos.utils import payment

		payment.process_payment(theirs, payments=[{"method": "Cash", "amount": float(theirs.total_amount)}])

		self._as_cashier()
		self.assertNotIn(theirs.name, {row["name"] for row in api.list_orders(self.profile, "closed")})

	def test_the_mixed_view_shows_the_floor_but_not_their_history(self):
		"""`all` is the one view holding both, so its closed half is filtered
		after the query rather than by a filter that would hide open bills too."""
		still_open = self._order()

		settled = self._order()
		service.add_item(settled, item=ITEM, qty=1)
		settled.save(ignore_permissions=True)
		settled.reload()

		from restaurant_pos.utils import payment

		payment.process_payment(settled, payments=[{"method": "Cash", "amount": float(settled.total_amount)}])

		self._as_cashier()
		names = {row["name"] for row in api.list_orders(self.profile, "all")}
		self.assertIn(still_open.name, names)
		self.assertNotIn(settled.name, names)


def _stamp(order_name: str, field: str, when: str) -> None:
	"""Move a bill's opening or closing time, without touching anything else."""
	frappe.db.set_value("Restaurant Order", order_name, field, when, update_modified=False)


class TestEachTabIsBoundedByItsOwnEvent(ReturnTestBase):
	"""`D-146` — the defect the user reported, and the two beside it.

	*"هذه الفواتير إذا أغلقتها لا تظهر ضمن الفواتير المغلقة"* — and they were
	right. All three history tabs measured **when the bill opened**, so a bill
	opened before midnight and paid after it disappeared from the till the
	moment it was paid: not on the floor any more, and not in today's history
	either. A restaurant that serves past midnight is the ordinary case, not the
	edge one.

	The rule these hold to is one sentence: **a tab is bounded by the event it
	is named after.** Closed today means closed today; refunds mean refunds
	taken today; the floor is not bounded at all, because a bill left open is
	still the cashier's whatever day it started.
	"""

	def _names(self, view: str) -> set[str]:
		return {row["name"] for row in api.list_orders(self.profile, view=view)}

	def test_a_bill_opened_yesterday_and_paid_today_is_in_todays_history(self):
		"""The user's own case, exactly."""
		order = self._paid()
		_stamp(order.name, "opened_at", f"{YESTERDAY} 23:40:00")

		self.assertIn(order.name, self._names("closed"))

	def test_a_bill_that_closed_yesterday_is_not(self):
		"""The other half — or "today" would just mean "ever"."""
		order = self._paid()
		_stamp(order.name, "closed_at", f"{YESTERDAY} 23:40:00")

		self.assertNotIn(order.name, self._names("closed"))

	def test_a_bill_still_open_from_yesterday_is_always_on_the_floor(self):
		"""A tab running past midnight, or carried over by `D-105`."""
		order = self._order()
		service.add_item(order, item=ITEM, qty=1)
		_stamp(order.name, "opened_at", f"{YESTERDAY} 21:00:00")

		self.assertIn(order.name, self._names("open"))
		self.assertIn(order.name, self._names("all"))

	def test_the_mixed_view_is_bounded_too(self):
		"""`all` had no limit and no date at all — the branch's whole history."""
		order = self._paid()
		_stamp(order.name, "closed_at", f"{YESTERDAY} 23:40:00")

		self.assertNotIn(order.name, self._names("all"))

	def test_a_refund_taken_today_on_an_older_bill_is_listed(self):
		"""`BR-055` exists because refunding an older bill happens.

		It takes a manager's PIN — and then the refund did not appear in the
		tab that exists to show the day's refunds, while the drawer it was paid
		out of counted it.
		"""
		order = self._paid()
		refund = returns.create_return(order, items=[{"row": self._row(order), "qty": 1}], reason_code=REASON)
		_stamp(order.name, "opened_at", f"{YESTERDAY} 20:00:00")
		_stamp(order.name, "closed_at", f"{YESTERDAY} 20:30:00")

		rows = api.list_orders(self.profile, view="returned")
		self.assertIn(refund["credit_note"], {row["credit_note"] for row in rows})

	def test_a_refund_taken_yesterday_is_not_in_todays(self):
		order = self._paid()
		refund = returns.create_return(order, items=[{"row": self._row(order), "qty": 1}], reason_code=REASON)
		frappe.db.set_value(
			"Sales Invoice", refund["credit_note"], "creation", f"{YESTERDAY} 20:00:00", update_modified=False
		)

		rows = api.list_orders(self.profile, view="returned")
		self.assertNotIn(refund["credit_note"], {row["credit_note"] for row in rows})

	def test_the_all_tab_holds_the_refunds_too(self):
		"""`D-151` — the tab named for everything held everything but them."""
		order = self._paid()
		refund = returns.create_return(
			order, items=[{"row": self._row(order), "qty": 1}], reason_code=REASON
		)

		rows = api.list_orders(self.profile, view="all")
		self.assertIn(refund["credit_note"], {row.get("credit_note") for row in rows})

	def test_the_all_tab_still_holds_the_floor_and_the_history(self):
		"""And adding them took nothing away."""
		open_bill = self._order()
		service.add_item(open_bill, item=ITEM, qty=1)
		closed = self._paid()

		names = {row["name"] for row in api.list_orders(self.profile, view="all")}
		self.assertIn(open_bill.name, names)
		self.assertIn(closed.name, names)

	def test_a_refund_row_is_dated_by_the_refund(self):
		"""Not by the sale, which may be any age (`D-143`)."""
		order = self._paid()
		refund = returns.create_return(order, items=[{"row": self._row(order), "qty": 1}], reason_code=REASON)
		_stamp(order.name, "opened_at", f"{YESTERDAY} 20:00:00")
		_stamp(order.name, "closed_at", f"{YESTERDAY} 20:30:00")

		row = next(
			entry
			for entry in api.list_orders(self.profile, view="returned")
			if entry["credit_note"] == refund["credit_note"]
		)
		self.assertEqual(str(row["opened_at"])[:10], nowdate())
		self.assertEqual(str(row["closed_at"])[:10], nowdate())

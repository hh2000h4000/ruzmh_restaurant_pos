# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Which promotion applies, and what it takes off (`FR-11`, `D-163`).

**A promotion is configuration that spends the restaurant's money**, and it does
so without anybody at the till agreeing to it. So the rules that decide *which*
one applies matter more than the arithmetic: two promotions quietly compounding
produce a figure nobody sized, and it is discovered with a customer standing
there.

The three rules, researched before they were written:

1. a single item is never touched by two promotions;
2. **priority** decides first — a number a manager sets;
3. on a tie, the **greater discount** wins, which the user chose and which makes
   an unset priority safe rather than arbitrary.

Refs: FR-11.1, FR-11.2, BR-032, BR-033, BR-034, BR-035, D-074, D-163
"""

from contextlib import contextmanager
from datetime import timedelta

import frappe

from restaurant_pos.api import order as api_order
from restaurant_pos.tests.test_order import ITEM, OrderTestBase
from restaurant_pos.utils import order as orders
from restaurant_pos.utils import promotions, totals


class PromotionTestBase(OrderTestBase):
	"""A bill with one 25-riyal line, and promotions this test owns outright."""

	def setUp(self):
		self._clear()

	def tearDown(self):
		self._clear()

	def _clear(self) -> None:
		for name in frappe.get_all(
			"Restaurant Promotion", filters={"title": ("like", "RPOS test%")}, pluck="name"
		):
			frappe.delete_doc("Restaurant Promotion", name, force=True, ignore_permissions=True)

	def _promotion(self, **fields):
		defaults = {
			"doctype": "Restaurant Promotion",
			"title": "RPOS test promotion",
			"title_ar": "عرض اختبار",
			"is_active": 1,
			"is_auto_apply": 1,
			"promotion_type": "percentage",
			"discount_value": 10,
			"apply_to": "all",
			"item_scope": "all",
		}
		return frappe.get_doc(defaults | fields).insert(ignore_permissions=True)

	def _bill(self, qty: float = 1):
		order = self._order()
		orders.add_item(order, item=ITEM, qty=qty)
		order.reload()
		return order


class WhichPromotionWins(PromotionTestBase):
	def test_a_bill_with_no_promotion_gets_none(self):
		self.assertIsNone(promotions.best_for(self._bill()))

	def test_an_auto_promotion_applies_itself(self):
		self._promotion(title="RPOS test ten", discount_value=10)

		order = self._bill()

		self.assertEqual(order.promotion_amount, 2.5)
		self.assertEqual(order.discount_amount, 2.5)

	def test_priority_decides_before_the_amount(self):
		"""A manager's number outranks the arithmetic — that is what it is for."""
		self._promotion(title="RPOS test small but first", discount_value=5, priority=100)
		self._promotion(title="RPOS test big but second", discount_value=40, priority=10)

		chosen = promotions.best_for(self._bill())

		self.assertEqual(chosen.title, "RPOS test small but first")

	def test_a_tie_goes_to_the_customer(self):
		"""The user's choice, and what makes an unset priority safe: with nobody
		having ranked them, the shop never accidentally gives less than it
		advertised."""
		self._promotion(title="RPOS test lesser", discount_value=5)
		self._promotion(title="RPOS test greater", discount_value=25)

		chosen = promotions.best_for(self._bill())

		self.assertEqual(chosen.title, "RPOS test greater")

	def test_only_one_applies(self):
		"""`BR-034` and `BR-035` both hold, and this is the line between them: two
		promotions may apply to one **bill**, on different items — and no single
		item is ever discounted twice. Here both cover the whole bill, so one
		wins outright rather than compounding to 36%."""
		self._promotion(title="RPOS test twenty", discount_value=20)
		self._promotion(title="RPOS test other twenty", discount_value=20)

		order = self._bill()

		self.assertEqual(order.promotion_amount, 5.0, "20% of 25, not 36%")

	def test_a_manual_promotion_is_not_applied_by_itself(self):
		"""`is_auto_apply` off means the cashier chooses it — it is offered, not taken."""
		self._promotion(title="RPOS test manual", is_auto_apply=0, discount_value=50)

		order = self._bill()

		self.assertEqual(order.promotion_amount, 0.0)
		self.assertIn("RPOS test manual", [row.title for row in promotions.active_for(order)])


class WhenAPromotionDoesNotApply(PromotionTestBase):
	def test_an_inactive_one_never_does(self):
		self._promotion(title="RPOS test off", is_active=0, discount_value=50)

		self.assertEqual(self._bill().promotion_amount, 0.0)

	def test_one_whose_dates_have_passed(self):
		self._promotion(
			title="RPOS test expired",
			valid_from="2026-01-01",
			valid_to="2026-01-31",
			discount_value=50,
		)

		self.assertEqual(self._bill().promotion_amount, 0.0)

	def test_one_below_its_minimum(self):
		"""The condition the research calls essential and we had no field for."""
		self._promotion(title="RPOS test big spenders", min_order_amount=1000, discount_value=50)

		self.assertEqual(self._bill().promotion_amount, 0.0)

	def test_but_it_does_once_the_bill_reaches_the_minimum(self):
		self._promotion(title="RPOS test big spenders", min_order_amount=50, discount_value=10)

		order = self._bill(qty=4)  # 100.00

		self.assertEqual(order.promotion_amount, 10.0)

	def test_one_scoped_to_another_order_type(self):
		self._promotion(
			title="RPOS test elsewhere",
			apply_to="by_order_type",
			discount_value=50,
			applicable_order_types=[{"order_type": self.dine_in}],
		)

		# The bill is a takeaway, so a dine-in promotion is not its business.
		self.assertEqual(self._bill().promotion_amount, 0.0)


class TheMoneyIsNeverGivenBack(PromotionTestBase):
	def test_a_voucher_larger_than_the_bill_takes_only_the_bill(self):
		self._promotion(title="RPOS test voucher", promotion_type="fixed_amount", discount_value=500)

		order = self._bill()  # 25.00

		self.assertEqual(order.promotion_amount, 25.0)
		self.assertEqual(order.total_amount, 0.0)

	def test_it_never_exceeds_what_a_manual_discount_left(self):
		"""Two reductions that together beat the bill would hand money back, and
		the cashier would find out at the payment screen."""
		self._promotion(title="RPOS test voucher", promotion_type="fixed_amount", discount_value=500)

		order = self._bill()
		# The discount lives on the order and is applied through the payment
		# flow; what matters here is the two reductions meeting, so it is set
		# directly and the totals recomputed.
		order.discount_type = "percentage"
		order.discount_value = 100
		order.save(ignore_permissions=True)
		order.reload()

		self.assertGreaterEqual(order.total_amount, 0.0)
		self.assertLessEqual(order.discount_amount, order.subtotal)


class TheHappyHour(PromotionTestBase):
	"""The window a promotion runs in — and the two ways it was silently wrong.

	This class exists because of a test that failed one run in three. The cause
	was not the test: **Frappe stamps every `Time` field with the current clock
	on insert** (`create_new.py:149`), so a promotion saved with no hours held
	the same instant in both fields, and was outside its own window one second
	later. Every promotion a manager created without touching those fields was
	dead on arrival, and said nothing about it (`D-074`, `D-163`).
	"""

	def test_a_promotion_with_no_hours_runs_all_day(self):
		"""The one that was failing. It must hold at every moment, not most."""
		promo = self._promotion(title="RPOS test all day", discount_value=10)

		self.assertIsNone(promo.time_from, "the framework's stamp is not a window")
		self.assertIsNone(promo.time_to)

		for hour in range(24):
			with self.subTest(hour=hour), self._clock(f"{hour:02d}:30:00"):
				self.assertTrue(promotions._within_hours(self._row(promo)))

	def test_the_stamp_is_gone_from_the_stored_row_too(self):
		"""Not only the in-memory document: the engine reads the database."""
		promo = self._promotion(title="RPOS test all day", discount_value=10)

		row = self._row(promo)

		self.assertIsNone(row.time_from)
		self.assertIsNone(row.time_to)

	def test_a_row_saved_before_the_fix_still_runs_all_day(self):
		"""The rows already in the database still carry the stamp.

		Clearing it on save fixes what is saved from now on and nothing that was
		saved before, so the engine has to hold the same line — otherwise every
		promotion created up to today stays dead and the fix looks like it worked.
		"""
		stamped = frappe.get_all(
			"Restaurant Promotion",
			filters={"name": self._promotion(title="RPOS test old", discount_value=10).name},
			fields=list(promotions.FIELDS),
		)[0]
		# What Frappe wrote. The two fields are stamped by two separate calls to
		# the clock, so they are microseconds apart — and here they land either
		# side of a second boundary. That is the case worth pinning: while they
		# share a second, treating the window as empty and reading it as a range
		# happen to agree, and the guard only earns its place on the run where
		# they do not.
		stamped.time_from = timedelta(seconds=70646, microseconds=999_812)
		stamped.time_to = timedelta(seconds=70647, microseconds=4_133)

		for hour in range(24):
			with self.subTest(hour=hour), self._clock(f"{hour:02d}:30:00"):
				self.assertTrue(promotions._within_hours(stamped))

	def test_a_morning_window_is_read_as_a_time_not_as_text(self):
		"""`9:00:00` sorts after `16:00:00` as text. Every morning offer would
		have been wrong, and the arithmetic would have looked fine."""
		promo = self._promotion(title="RPOS test breakfast", time_from="09:00:00", time_to="11:00:00")
		row = self._row(promo)

		with self._clock("10:00:00"):
			self.assertTrue(promotions._within_hours(row))
		with self._clock("16:00:00"):
			self.assertFalse(promotions._within_hours(row))
		with self._clock("08:00:00"):
			self.assertFalse(promotions._within_hours(row))

	def test_a_window_that_runs_past_midnight_is_one_window(self):
		promo = self._promotion(title="RPOS test late", time_from="22:00:00", time_to="02:00:00")
		row = self._row(promo)

		for now, inside in (("23:00:00", True), ("01:00:00", True), ("15:00:00", False)):
			with self.subTest(now=now), self._clock(now):
				self.assertIs(promotions._within_hours(row), inside)

	def test_a_promotion_outside_its_hours_takes_nothing(self):
		"""The whole point of the window, proved through the bill rather than the
		helper — a condition that is right in isolation and unwired is still a
		promotion that fires when it should not."""
		self._promotion(title="RPOS test breakfast", time_from="09:00:00", time_to="09:30:00")

		with self._clock("20:00:00"):
			self.assertEqual(self._bill().promotion_amount, 0.0)

	def _row(self, promo):
		"""The promotion as the engine reads it — `get_all`, not the document.

		The two differ: the database hands a `Time` column back as a `timedelta`
		and the document as a string, and the bug lived in that gap.
		"""
		return frappe.get_all(
			"Restaurant Promotion", filters={"name": promo.name}, fields=list(promotions.FIELDS)
		)[0]

	@contextmanager
	def _clock(self, now: str):
		"""Hold the clock still. Otherwise these tests pass by the hour they run."""
		real = promotions.nowtime
		promotions.nowtime = lambda: now
		try:
			yield
		finally:
			promotions.nowtime = real


class TheBillSaysWhichPromotion(PromotionTestBase):
	"""Money came off; something has to name the rule that took it (`D-163`).

	A total that drops with nothing saying why is the report a manager cannot act
	on, and the cashier standing in front of the guest cannot answer either
	(`D-074`). So the name travels with the bill rather than being looked up
	client-side against a cached list a new promotion is not in yet.
	"""

	def test_the_payload_names_the_promotion_that_applied(self):
		self._promotion(title="RPOS test breakfast", title_ar="عرض الإفطار", discount_value=10)

		payload = api_order._summary(self._bill())

		self.assertEqual(payload["promotion_amount"], 2.5)
		self.assertEqual(payload["promotion_title"], "RPOS test breakfast")
		self.assertEqual(payload["promotion_title_ar"], "عرض الإفطار")

	def test_a_bill_with_no_promotion_names_none(self):
		payload = api_order._summary(self._bill())

		self.assertEqual(payload["promotion_amount"], 0.0)
		self.assertEqual(payload["promotion_title"], "")

	def test_the_manual_discount_can_be_told_from_the_promotion(self):
		"""The two are folded into `discount_amount` so the tax is worked out
		once — and the screens subtract to separate them, so the promotion has to
		be reported as its own figure or a manager approving a discount is shown
		an offer nobody asked them about."""
		self._promotion(title="RPOS test breakfast", discount_value=10)

		order = self._bill()
		# The discount is applied through the payment flow, which recalculates
		# and then saves — a plain `save` does neither, so doing it that way
		# would assert against the figures `add_item` left behind.
		order.discount_type = "amount"
		order.discount_value = 5
		totals.calculate(order)
		order.save(ignore_permissions=True)
		order.reload()

		payload = api_order._summary(order)

		self.assertEqual(payload["promotion_amount"], 2.5)
		self.assertEqual(payload["discount_amount"] - payload["promotion_amount"], 5.0)


class ASilentPromotionIsRefused(PromotionTestBase):
	"""`D-074` — the DocType offers a type it carries no data for.

	A manager could choose *buy X get Y*, save, and get a promotion that looks
	configured and does nothing. There is nowhere on the record to say how many
	to buy or how many to get, so it is refused at the door and the fields will
	arrive with the reward that needs them.
	"""

	def test_buy_x_get_y_says_it_is_not_available(self):
		with self.assertRaises(frappe.ValidationError):
			self._promotion(title="RPOS test bogo", promotion_type="buy_x_get_y", discount_value=1)

	def test_a_free_item_needs_an_item_or_a_group(self):
		with self.assertRaises(frappe.ValidationError):
			self._promotion(title="RPOS test free", promotion_type="free_item")

	def test_and_not_both(self):
		"""Two answers to one question: which item is the guest being given?"""
		with self.assertRaises(frappe.ValidationError):
			self._promotion(
				title="RPOS test free",
				promotion_type="free_item",
				free_item=ITEM,
				free_item_group=frappe.db.get_value("Item", ITEM, "item_group"),
			)

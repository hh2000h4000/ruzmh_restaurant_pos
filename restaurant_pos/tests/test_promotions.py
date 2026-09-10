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
from frappe.utils import flt

from restaurant_pos.api import order as api_order
from restaurant_pos.api import payment as api_payment
from restaurant_pos.tests.test_order import ITEM, OrderTestBase, _make_cashier
from restaurant_pos.tests.test_payment import CASH
from restaurant_pos.utils import activity, promotions, totals
from restaurant_pos.utils import order as orders
from restaurant_pos.utils import payment as payment_service


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

	def test_half_a_window_is_refused(self):
		"""`D-170` — and until the form stopped stamping, this could never fire.

		`bool(time_from) != bool(time_to)` has been on the record all along and
		was unreachable: the framework filled *both* fields the moment the form
		opened, so there was no such thing as half a window to refuse. A manager
		who set only the end time kept a start of whenever they opened the form.

		With the stamp cleared at the source, half a window is a real state, and
		this is what happens to it.
		"""
		promo = self._promotion(title="RPOS test half")
		promo.time_to = "17:00:00"

		with self.assertRaises(frappe.ValidationError):
			promo.save(ignore_permissions=True)

	def test_a_window_a_manager_actually_set_is_kept(self):
		"""The other half of it: clearing the stamp must not clear a real window."""
		promo = self._promotion(title="RPOS test evening", time_from="15:00:00", time_to="17:00:00")

		self.assertIsNotNone(promo.time_from)
		self.assertIsNotNone(promo.time_to)

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


class TheCashierCanChooseOne(PromotionTestBase):
	"""`is_auto_apply = 0` means *offered*, and there was nothing to offer it on.

	The engine shipped returning these promotions from `active_for` and no
	endpoint called it, no screen drew it, and nothing applied it — a manager
	could configure a manual promotion, save it, see it listed as active, and it
	did nothing at all. **The same defect this module refuses `buy_x_get_y` at
	the door for** (`D-074`), one field over (`D-165`).
	"""

	def test_a_manual_promotion_is_on_offer(self):
		self._promotion(title="RPOS test manual", is_auto_apply=0, discount_value=20)

		offers = promotions.offers_for(self._bill())

		self.assertEqual([offer["title"] for offer in offers], ["RPOS test manual"])
		self.assertEqual(offers[0]["benefit"], 5.0)
		self.assertEqual(offers[0]["is_auto_apply"], 0)

	def test_choosing_it_applies_it(self):
		promo = self._promotion(title="RPOS test manual", is_auto_apply=0, discount_value=20)

		order = self._bill()
		order.chosen_promotion = promo.name
		totals.calculate(order)

		self.assertEqual(order.promotion, promo.name)
		self.assertEqual(order.promotion_amount, 5.0)

	def test_a_choice_outranks_the_engines_own_pick(self):
		"""Priority and the better-deal tiebreak decide when *nobody* decided.

		Here somebody has — and an automatic pick that overrode them would make
		`is_auto_apply = 0` mean nothing: listed, chosen, quietly replaced.
		"""
		self._promotion(title="RPOS test auto", discount_value=40, priority=100)
		picked = self._promotion(title="RPOS test manual", is_auto_apply=0, discount_value=20)

		order = self._bill()
		order.chosen_promotion = picked.name
		totals.calculate(order)

		self.assertEqual(order.promotion, picked.name)
		self.assertEqual(order.promotion_amount, 5.0, "20% of 25, not the automatic 40%")

	def test_a_choice_is_still_held_to_the_conditions(self):
		"""Choosing does not exempt a promotion from its own record: one whose
		dates have passed is simply not on offer, and picking it changes nothing.
		"""
		expired = self._promotion(
			title="RPOS test expired",
			is_auto_apply=0,
			valid_from="2026-01-01",
			valid_to="2026-01-31",
			discount_value=50,
		)

		order = self._bill()
		order.chosen_promotion = expired.name
		totals.calculate(order)

		self.assertIsNone(order.promotion)
		self.assertEqual(order.promotion_amount, 0.0)

	def test_the_offer_says_which_one_is_chosen(self):
		promo = self._promotion(title="RPOS test manual", is_auto_apply=0, discount_value=20)

		order = self._bill()
		order.chosen_promotion = promo.name

		self.assertEqual(promotions.offers_for(order)[0]["is_chosen"], 1)


class ChoosingOneIsSpendingTheShopsMoney(PromotionTestBase):
	"""The two checks on the server, because the screen is not a check (§5.4)."""

	def _pay(self, order, promotion):
		return payment_service.process_payment(
			order,
			payments=[{"method": CASH, "amount": order.total_amount}],
			promotion=promotion,
		)

	def test_a_promotion_not_on_offer_is_refused(self):
		"""Without this a cashier could name any promotion in the system — an
		expired one, or one scoped to another branch — and the engine would
		honour it, which turns every condition on the record into a suggestion.
		"""
		elsewhere = self._promotion(
			title="RPOS test elsewhere",
			is_auto_apply=0,
			apply_to="by_order_type",
			discount_value=50,
			applicable_order_types=[{"order_type": self.dine_in}],
		)

		order = self._bill()

		with self.assertRaises(frappe.ValidationError):
			self._pay(order, elsewhere.name)

	def test_a_cashier_without_the_right_is_refused(self):
		"""Runs as a real cashier on purpose: as Administrator every right is
		held, so asserting against the default test user would prove nothing
		(`D-144`, `D-157`).
		"""
		promo = self._promotion(title="RPOS test manual", is_auto_apply=0, discount_value=20)
		order = self._bill()
		cashier = _make_cashier()

		frappe.set_user(cashier)
		frappe.local.rpos_permission_cache = {}
		try:
			with self.assertRaises(frappe.ValidationError):
				self._pay(order, promo.name)
		finally:
			frappe.set_user("Administrator")
			frappe.local.rpos_permission_cache = {}

	def test_choosing_one_by_hand_is_audited(self):
		"""**Two logs, two questions** (`D-172`, `08` §5).

		The bill's story carries every offer that reached it, automatic or not.
		The audit log carries the ones a *person* chose — spending the shop's
		money under a permission, the same class of act as a discount beyond a
		ceiling. An automatic offer is the shop's own rule firing and has no
		place there; this one does.
		"""
		promo = self._promotion(title="RPOS test manual", is_auto_apply=0, discount_value=20)
		order = self._bill()

		self._pay(order, promo.name)

		audited = frappe.get_all(
			"POS Audit Log",
			filters={"restaurant_order": order.name, "action_type": "promotion_applied"},
			pluck="reason",
		)
		self.assertEqual(audited, [promo.name])

	def test_an_automatic_one_is_not_audited(self):
		"""It belongs on the story, not in the compliance record — folding them
		together buries the override worth finding under a day of routine."""
		self._promotion(title="RPOS test auto", discount_value=10)
		order = self._bill()

		self._pay(order, None)

		self.assertEqual(
			frappe.get_all(
				"POS Audit Log",
				filters={"restaurant_order": order.name, "action_type": "promotion_applied"},
			),
			[],
		)

	def test_the_invoice_names_the_promotion_that_actually_applied(self):
		"""It used to name whatever string the client sent — written onto a
		submitted financial document with nothing checking it, explaining a total
		that had been worked out from something else entirely.
		"""
		promo = self._promotion(title="RPOS test manual", is_auto_apply=0, discount_value=20)
		order = self._bill()

		self._pay(order, promo.name)
		order.reload()

		remarks = frappe.db.get_value("Sales Invoice", order.sales_invoice, "remarks") or ""
		self.assertIn("RPOS test manual", remarks)


class WhichLineTheOfferCameOff(PromotionTestBase):
	"""`D-166` — the bill's total cannot answer it.

	A bill that says "-13.00" at the bottom does not say which dish it came off,
	and that is the question the guest asks while pointing at one. It matters
	most on the bill this engine was built for: an offer scoped to some items,
	sitting on a bill that also holds items it never touched.
	"""

	@classmethod
	def setUpClass(cls):
		"""A second sellable item, which the shared base does not have.

		`OrderTestBase` sells exactly one, and the case this class exists for
		needs a bill holding something the offer reaches **and** something it
		does not. Created here rather than in the shared fixture: one class needs
		it, and a second item in everyone's price list would quietly change what
		every other money assertion is measuring (`D-155`).
		"""
		super().setUpClass()
		cls.other_item = "RPOS-TEST-JUICE"

		if not frappe.db.exists("Item", cls.other_item):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": cls.other_item,
					"item_name": "RPOS Test Juice",
					"pos_display_name_ar": "عصير الاختبار",
					"item_group": frappe.db.get_value("Item", ITEM, "item_group"),
					"stock_uom": "Nos",
					"is_stock_item": 0,
					"is_sales_item": 1,
					"include_item_in_manufacturing": 0,
				}
			).insert(ignore_permissions=True)

		existing = frappe.db.get_value(
			"Item Price", {"item_code": cls.other_item, "price_list": cls.price_list}, "name"
		)
		if existing:
			frappe.db.set_value("Item Price", existing, "price_list_rate", 25)
		else:
			frappe.get_doc(
				{
					"doctype": "Item Price",
					"item_code": cls.other_item,
					"price_list": cls.price_list,
					"selling": 1,
					"price_list_rate": 25,
				}
			).insert(ignore_permissions=True)

		frappe.db.commit()

	def _mixed_bill(self):
		"""One line the offer can reach and one it cannot."""
		order = self._order()
		orders.add_item(order, item=ITEM, qty=1)
		orders.add_item(order, item=self.other_item, qty=1)
		order.reload()
		return order

	def test_a_whole_bill_offer_marks_every_line(self):
		self._promotion(title="RPOS test ten", discount_value=10)

		order = self._bill(qty=2)  # 50.00

		self.assertEqual(promotions.per_line(order), {1: 5.0})

	def test_a_scoped_offer_marks_only_the_lines_it_reached(self):
		"""The case the totals row cannot answer."""
		self._promotion(
			title="RPOS test drinks",
			discount_value=50,
			item_scope="specific_items",
			applicable_items=[{"item": ITEM}],
		)

		order = self._mixed_bill()
		marks = promotions.per_line(order)

		self.assertEqual(set(marks), {1}, "only the line the offer reached")
		self.assertEqual(marks[1], 12.5, "half of the 25 riyal line, not of the bill")

	def test_each_line_takes_its_own_share_and_not_its_own_price(self):
		"""**Two covered lines of different sizes, which is where a split can go
		wrong without the sum noticing.**

		Every other test here has one covered line, so the last-line remainder
		answers them all and the proportional step is never exercised: a line
		could claim its whole price came off and the total would still balance,
		because the remainder absorbs it. A cashier would read "-75.00" against a
		75 riyal dish on a bill that lost ten.
		"""
		self._promotion(title="RPOS test ten", discount_value=10)

		order = self._order()
		orders.add_item(order, item=ITEM, qty=1)  # 25.00
		orders.add_item(order, item=ITEM, qty=3)  # 75.00
		order.reload()

		self.assertEqual(promotions.per_line(order), {1: 2.5, 2: 7.5})

	def test_the_shares_add_up_to_the_figure_on_the_bill(self):
		"""**Exactly**, not to a cent beside it.

		A receipt whose lines do not sum to its total is read as a mistake by the
		one person who cannot check it — the same defect class as the guest
		screen's `60.00 + 7.83 = 60.00` (`D-162`). A third of a third is where
		proportional shares drift, so the last line takes the remainder.
		"""
		self._promotion(title="RPOS test third", discount_value=33.33)

		order = self._order()
		for qty in (1, 1, 1):
			orders.add_item(order, item=ITEM, qty=qty)
		order.reload()

		marks = promotions.per_line(order)

		self.assertEqual(flt(sum(marks.values()), 2), order.promotion_amount)

	def test_a_bill_with_no_offer_marks_nothing(self):
		self.assertEqual(promotions.per_line(self._bill()), {})

	def test_a_voided_line_is_never_marked(self):
		"""It is not part of what is owed, so it is not part of what was taken off."""
		self._promotion(title="RPOS test ten", discount_value=10)

		order = self._mixed_bill()
		orders.void_item(order, item_idx=2, reason="RPOS test")
		order.reload()

		self.assertNotIn(2, promotions.per_line(order))

	def test_the_payload_carries_the_mark_to_the_screen(self):
		"""A share the screen never receives is a share nobody can see."""
		self._promotion(
			title="RPOS test drinks",
			discount_value=50,
			item_scope="specific_items",
			applicable_items=[{"item": ITEM}],
		)

		order = self._mixed_bill()
		lines = api_order.get_order(order.name)["items"]

		self.assertEqual(lines[0]["promotion_amount"], 12.5)
		self.assertEqual(lines[1]["promotion_amount"], 0.0)


class AGroupMeansEverythingUnderIt(PromotionTestBase):
	"""`D-169` — `Item Group` is a tree, and no item lives in a parent.

	A manager who scopes an offer to *Drinks* means every drink. Matching the
	item's own group alone would cover none of them, because the items hang off
	*Hot drinks* and *Cold drinks* beneath it. And it fails in the direction that
	costs quietly: the promotion saves, reads as active, covers nothing, and the
	shop learns of it from a guest who was promised an offer.
	"""

	@classmethod
	def setUpClass(cls):
		"""A two-level menu: a parent group with the sellable item under a child."""
		super().setUpClass()
		cls.parent_group = "RPOS Test Drinks"
		cls.child_group = "RPOS Test Cold Drinks"
		root = frappe.db.get_value(
			"Item Group", {"is_group": 1, "parent_item_group": ("is", "not set")}, "name"
		)

		for name, parent, is_group in (
			(cls.parent_group, root, 1),
			(cls.child_group, cls.parent_group, 0),
		):
			if not frappe.db.exists("Item Group", name):
				frappe.get_doc(
					{
						"doctype": "Item Group",
						"item_group_name": name,
						"parent_item_group": parent,
						"is_group": is_group,
					}
				).insert(ignore_permissions=True)

		cls.original_group = frappe.db.get_value("Item", ITEM, "item_group")
		frappe.db.set_value("Item", ITEM, "item_group", cls.child_group)
		frappe.clear_cache(doctype="Item")
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.db.rollback()
		frappe.db.set_value("Item", ITEM, "item_group", cls.original_group)
		frappe.clear_cache(doctype="Item")
		frappe.db.commit()
		super().tearDownClass()

	def test_choosing_the_parent_covers_the_item_beneath_it(self):
		"""The case the user described: pick *Drinks*, get every drink."""
		self._promotion(
			title="RPOS test drinks",
			discount_value=10,
			item_scope="specific_groups",
			applicable_item_groups=[{"item_group": self.parent_group}],
		)

		self.assertEqual(self._bill().promotion_amount, 2.5)

	def test_choosing_the_child_still_works(self):
		self._promotion(
			title="RPOS test cold",
			discount_value=10,
			item_scope="specific_groups",
			applicable_item_groups=[{"item_group": self.child_group}],
		)

		self.assertEqual(self._bill().promotion_amount, 2.5)

	def test_a_group_the_item_is_not_under_covers_nothing(self):
		"""Descending the tree must not turn every group into every item."""
		elsewhere = frappe.db.get_value(
			"Item Group", {"is_group": 0, "name": ("not in", [self.child_group])}, "name"
		)
		self._promotion(
			title="RPOS test elsewhere",
			discount_value=50,
			item_scope="specific_groups",
			applicable_item_groups=[{"item_group": elsewhere}],
		)

		self.assertEqual(self._bill().promotion_amount, 0.0)


class AnExclusiveOfferRefusesADiscount(PromotionTestBase):
	"""`is_exclusive` was a checkbox nobody read (`D-169`).

	It sat on the record, went out to the client, and no line of code acted on
	it: a manager could tick *does not combine with a manual discount* and the
	till would take both — the shop giving away twice what it agreed to, while
	the record insisted otherwise.
	"""

	def _pay_with_discount(self, order, percentage=10):
		return payment_service.process_payment(
			order,
			payments=[{"method": CASH, "amount": order.total_amount}],
			discount_type="percentage",
			discount_value=percentage,
		)

	def test_the_discount_is_refused_and_the_offer_is_named(self):
		"""A refusal that will not say *which* offer is unactionable."""
		self._promotion(title="RPOS test national day", title_ar="عرض اليوم الوطني", is_exclusive=1)

		order = self._bill()

		with self.assertRaises(frappe.ValidationError) as refusal:
			self._pay_with_discount(order)

		self.assertIn("عرض اليوم الوطني", str(refusal.exception))

	def test_an_ordinary_offer_still_combines(self):
		"""The flag is the rule; without it nothing changes."""
		self._promotion(title="RPOS test ordinary", is_exclusive=0)

		order = self._bill()
		self._pay_with_discount(order)
		order.reload()

		self.assertEqual(order.status, "closed")

	def test_the_screen_is_told_before_the_cashier_types(self):
		"""`D-125` — every condition the server refuses at Confirm is on the
		screen before it. A wall with no sign on it is the defect."""
		self._promotion(title="RPOS test national day", title_ar="عرض اليوم الوطني", is_exclusive=1)

		order = self._bill()

		self.assertEqual(api_payment.preview_totals(order.name)["discount_blocked_by"], "عرض اليوم الوطني")

	def test_and_nothing_is_blocked_when_no_offer_says_so(self):
		self.assertEqual(api_payment.preview_totals(self._bill().name)["discount_blocked_by"], "")


class TheBillsStorySaysTheOfferHappened(PromotionTestBase):
	"""`D-172` — money came off and the story said nothing.

	The user's own bill: 82.00 settled at 46.00 because an offer took 36.00, and
	its timeline read *opened · item added · item added · item added*. Anything
	that happens to a bill is written down, and this was the one movement that
	changed the total without a person doing it — so the only record of it was
	the total itself.
	"""

	def _story(self, order):
		return [(row["action"], row["subject"]) for row in activity.timeline(order.name)]

	def test_an_offer_that_applies_is_written_down(self):
		self._promotion(title="RPOS test ten", title_ar="عرض العشرة", discount_value=10)

		order = self._bill()

		applied = [row for row in self._story(order) if row[0] == "promotion_applied"]
		self.assertEqual(len(applied), 1)
		self.assertIn("عرض العشرة", applied[0][1])
		self.assertIn("2.50", applied[0][1])

	def test_it_is_written_once_and_not_on_every_tap(self):
		"""`totals.calculate` runs on every keystroke. A line per recalculation
		would bury the story it exists to tell."""
		self._promotion(title="RPOS test ten", discount_value=10)

		order = self._bill()
		orders.add_item(order, item=ITEM, qty=1)
		orders.add_item(order, item=ITEM, qty=1)
		order.reload()

		applied = [row for row in self._story(order) if row[0] == "promotion_applied"]
		self.assertEqual(len(applied), 1, "the offer arrived once; the bill grew three times")

	def test_swapping_one_offer_for_another_is_written_down(self):
		"""The bill crossing a minimum is a real event and changes what is owed."""
		self._promotion(title="RPOS test small", discount_value=5)
		self._promotion(title="RPOS test big spenders", min_order_amount=50, discount_value=40)

		order = self._bill()  # 25.00 — only the small one qualifies
		orders.add_item(order, item=ITEM, qty=3)  # 100.00 — the big one takes over
		order.reload()

		applied = [row for row in self._story(order) if row[0] == "promotion_applied"]
		self.assertEqual(len(applied), 2)

	def test_an_offer_falling_away_is_written_down(self):
		"""A bill dropping back under a minimum loses the offer, and the total
		goes up. Silence there is the same defect pointed the other way."""
		self._promotion(title="RPOS test big spenders", min_order_amount=50, discount_value=10)

		order = self._bill(qty=4)  # 100.00
		orders.set_item_qty(order, item_idx=1, qty=1)  # 25.00 — under the minimum
		order.reload()

		self.assertIn("promotion_removed", [row[0] for row in self._story(order)])

	def test_a_preview_leaves_no_trace(self):
		"""`preview_totals` recalculates in memory and never saves. A cashier
		reading what a discount would come to has not applied anything."""
		self._promotion(title="RPOS test ten", discount_value=10)

		order = self._bill()
		before = len(self._story(order))
		api_payment.preview_totals(order.name, "percentage", 10)

		self.assertEqual(len(self._story(order)), before)

	def test_a_bill_with_no_offer_says_nothing_about_offers(self):
		order = self._bill()

		self.assertEqual(
			[row for row in self._story(order) if row[0].startswith("promotion")],
			[],
		)


class BuyTwoGetTheThirdFree(PromotionTestBase):
	"""`D-173` — the offer the user named as what makes a promotions engine good.

	*Buy 2 get the 3rd free.* It needs no screen: the guest already ordered the
	dishes, so the offer takes the price of the free ones off lines that are on
	the bill. Three rules, all of them researched rather than invented —

	1. **the cheapest units are the free ones**, which is the only reading a
	   guest accepts: buy two get one on a kebab and a soup hands back the soup;
	2. **the offer repeats** — six units on *buy 2 get 1* give two free, not one;
	3. **units are counted across every line the offer covers**, not per dish, so
	   the same basket qualifies however the cashier keyed it.
	"""

	@classmethod
	def setUpClass(cls):
		"""A second item at a different price, so "cheapest" means something."""
		super().setUpClass()
		cls.cheap_item = "RPOS-TEST-WATER"

		if not frappe.db.exists("Item", cls.cheap_item):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": cls.cheap_item,
					"item_name": "RPOS Test Water",
					"pos_display_name_ar": "ماء الاختبار",
					"item_group": frappe.db.get_value("Item", ITEM, "item_group"),
					"stock_uom": "Nos",
					"is_stock_item": 0,
					"is_sales_item": 1,
					"include_item_in_manufacturing": 0,
				}
			).insert(ignore_permissions=True)

		existing = frappe.db.get_value(
			"Item Price", {"item_code": cls.cheap_item, "price_list": cls.price_list}, "name"
		)
		if existing:
			frappe.db.set_value("Item Price", existing, "price_list_rate", 5)
		else:
			frappe.get_doc(
				{
					"doctype": "Item Price",
					"item_code": cls.cheap_item,
					"price_list": cls.price_list,
					"selling": 1,
					"price_list_rate": 5,
				}
			).insert(ignore_permissions=True)

		frappe.db.commit()

	def _bogo(self, buy=2, get=1, **fields):
		return self._promotion(
			title="RPOS test bogo",
			title_ar="اشترِ ٢ والثالث مجاناً",
			promotion_type="buy_x_get_y",
			buy_qty=buy,
			get_qty=get,
			**fields,
		)

	def test_three_units_hand_one_back(self):
		self._bogo()

		order = self._bill(qty=3)  # 75.00

		self.assertEqual(order.promotion_amount, 25.0)
		self.assertEqual(order.subtotal - order.promotion_amount, 50.0)

	def test_two_units_are_not_enough(self):
		"""Below the threshold there is no offer — and it is not on offer either,
		because a promotion worth nothing is not something to show a cashier."""
		self._bogo()

		order = self._bill(qty=2)

		self.assertEqual(order.promotion_amount, 0.0)
		self.assertEqual([row.title for row in promotions.active_for(order)], [])

	def test_it_repeats_rather_than_firing_once(self):
		"""Six units give two free. An offer that fired once and stopped would be
		withdrawn mid-basket with nothing saying so."""
		self._bogo()

		order = self._bill(qty=6)  # 150.00

		self.assertEqual(order.promotion_amount, 50.0)

	def test_the_cheapest_units_are_the_free_ones(self):
		"""Two burgers at 25 and one water at 5: the water is what comes free."""
		self._bogo()

		order = self._order()
		orders.add_item(order, item=ITEM, qty=2)
		orders.add_item(order, item=self.cheap_item, qty=1)
		order.reload()

		self.assertEqual(order.promotion_amount, 5.0, "the water, not a burger")

	def test_units_are_counted_across_lines_not_per_dish(self):
		"""Two burgers and a water are three units, so the offer fires — even
		though no single line reaches three."""
		self._bogo()

		order = self._order()
		orders.add_item(order, item=ITEM, qty=2)
		orders.add_item(order, item=self.cheap_item, qty=1)
		order.reload()

		self.assertGreater(order.promotion_amount, 0)

	def test_the_mark_lands_on_the_line_that_lost_the_unit(self):
		"""**Not spread across the bill.** Specific units are free, so the marks
		are exactly those — worked out by the same function that priced them
		(`D-166`)."""
		self._bogo()

		order = self._order()
		orders.add_item(order, item=ITEM, qty=2)
		orders.add_item(order, item=self.cheap_item, qty=1)
		order.reload()

		self.assertEqual(promotions.per_line(order), {2: 5.0})

	def test_it_only_counts_the_items_it_covers(self):
		"""Scoped to one item, a bill of two others does not reach the threshold."""
		self._bogo(
			item_scope="specific_items",
			applicable_items=[{"item": self.cheap_item}],
		)

		order = self._order()
		orders.add_item(order, item=ITEM, qty=3)
		order.reload()

		self.assertEqual(order.promotion_amount, 0.0)

	def test_buy_one_get_one_takes_half_of_an_even_bill(self):
		"""The user's other example, and the arithmetic that catches an
		off-by-one: four units on *buy 1 get 1* are two free, not three."""
		self._bogo(buy=1, get=1)

		order = self._bill(qty=4)  # 100.00

		self.assertEqual(order.promotion_amount, 50.0)


class AKabsaAndAnyDrinkFree(BuyTwoGetTheThirdFree):
	"""`D-175` — the user's other example, and a decision of mine reversed.

	*Buy a kabsa, take any drink from the group free.* `D-163` shut this on the
	reasoning that naming a **group** leaves somebody to choose which drink, and
	choosing needs a screen.

	**It does not. The guest chooses by ordering.** They ask for a Pepsi, the
	cashier rings it, and the offer takes its price off a line already on the
	ticket — which is what the research says every till of this kind does: it
	discounts a line, it does not invent one.

	Inherits the two-price fixture from its neighbour, because "the cheapest one
	is the free one" needs two prices to mean anything.
	"""

	def _free_drink(self, **fields):
		"""Buy the burger, get the cheap item free."""
		return self._promotion(
			title="RPOS test kabsa",
			title_ar="كبسة ومشروب مجاناً",
			promotion_type="free_item",
			item_scope="specific_items",
			applicable_items=[{"item": ITEM}],
			free_item=self.cheap_item,
			**{"free_qty": 1, **fields},
		)

	def test_the_drink_on_the_bill_comes_free(self):
		self._free_drink()

		order = self._order()
		orders.add_item(order, item=ITEM, qty=1)  # 25.00 — the qualifier
		orders.add_item(order, item=self.cheap_item, qty=1)  # 5.00 — the reward
		order.reload()

		self.assertEqual(order.promotion_amount, 5.0)
		self.assertEqual(promotions.per_line(order), {2: 5.0})

	def test_it_never_adds_a_line_nobody_ordered(self):
		"""**The whole reason this needs no screen, and the line it must not
		cross.** A bill with the kabsa and no drink gets nothing: putting a drink
		on it would charge the guest nothing for it and tell the kitchen to make
		it."""
		self._free_drink()

		order = self._bill()  # the qualifier alone

		self.assertEqual(order.promotion_amount, 0.0)
		self.assertEqual(len(order.items), 1, "no line invented")

	def test_an_offer_that_can_give_nothing_is_not_on_offer(self):
		"""It used to be exempt from the worth-something test, because its value
		was a list price rather than money off this bill. Showing it to a cashier
		would be offering what cannot be given."""
		self._free_drink()

		self.assertEqual([row.title for row in promotions.active_for(self._bill())], [])

	def test_a_voided_drink_earns_nothing(self):
		"""**A line struck off the bill is not on the bill** (`D-175`).

		Found by mutation, not by reading: taking the void filter out of
		`_free_reward_units` left all eighty-one tests green. The guest orders
		the drink, changes their mind, the cashier voids it — and the offer went
		on taking its price off a drink nobody is being served. Money given away
		for nothing, on every bill it happened on.

		The engine's other half has excluded voids since it was written; this
		reward was added beside it and nothing held the same line here.
		"""
		self._free_drink()

		order = self._order()
		orders.add_item(order, item=ITEM, qty=1)  # the qualifier
		orders.add_item(order, item=self.cheap_item, qty=1)  # the reward
		orders.void_item(order, item_idx=2, reason="RPOS test")
		order.reload()

		self.assertEqual(order.promotion_amount, 0.0)
		self.assertEqual(promotions.per_line(order), {}, "nothing to mark")
		self.assertEqual(
			[row.title for row in promotions.active_for(order)],
			[],
			"and nothing left to offer",
		)

	def test_only_one_drink_comes_free_however_many_were_ordered(self):
		"""`free_qty` is the whole of it, and the cheapest is the free one."""
		self._free_drink()

		order = self._order()
		orders.add_item(order, item=ITEM, qty=1)
		orders.add_item(order, item=self.cheap_item, qty=3)  # 15.00
		order.reload()

		self.assertEqual(order.promotion_amount, 5.0, "one unit, not the line")

	def test_two_free_when_the_offer_says_two(self):
		self._free_drink(free_qty=2)

		order = self._order()
		orders.add_item(order, item=ITEM, qty=1)
		orders.add_item(order, item=self.cheap_item, qty=3)
		order.reload()

		self.assertEqual(order.promotion_amount, 10.0)

	def test_a_group_reward_takes_the_cheapest_in_it(self):
		"""*Any drink*, and the guest took two: the shop gives the cheaper."""
		self._promotion(
			title="RPOS test any drink",
			promotion_type="free_item",
			item_scope="specific_items",
			applicable_items=[{"item": ITEM}],
			free_item_group=frappe.db.get_value("Item", self.cheap_item, "item_group"),
			free_qty=1,
		)

		order = self._order()
		orders.add_item(order, item=ITEM, qty=1)  # 25.00 — also in the group
		orders.add_item(order, item=self.cheap_item, qty=1)  # 5.00
		order.reload()

		self.assertEqual(order.promotion_amount, 5.0, "the cheap one")

	def test_the_bill_has_to_qualify_first(self):
		"""A drink with no kabsa is a drink somebody pays for."""
		self._free_drink()

		order = self._order()
		orders.add_item(order, item=self.cheap_item, qty=1)
		order.reload()

		self.assertEqual(order.promotion_amount, 0.0)


class ASilentPromotionIsRefused(PromotionTestBase):
	"""`D-074` — a promotion that looks configured and does nothing.

	It reads as active in the list, and the shop finds out when a guest who was
	promised an offer does not get it.

	**Every reward is built now** (`D-173`, `D-175`), so nothing here is refused
	for being unavailable any more. What is still refused is a reward that is
	*half* configured: "buy 0", "get 0", or a free item that names neither an item
	nor a group. Each of those would save, read as active, and be discovered at
	the till.
	"""

	def test_a_buy_x_get_y_with_no_quantities_is_refused(self):
		"""Built now, and still not half-configurable.

		"Buy 0" is free food and "get 0" is an offer that gives nothing. Either
		would save, read as active, and be discovered at the till.
		"""
		for fields in ({"buy_qty": 0, "get_qty": 1}, {"buy_qty": 2, "get_qty": 0}, {}):
			with self.subTest(fields=fields), self.assertRaises(frappe.ValidationError):
				self._promotion(title="RPOS test bogo", promotion_type="buy_x_get_y", **fields)

	def test_a_free_item_needs_an_item_or_a_group(self):
		"""Built now (`D-175`), and still not half-configurable: a reward that
		names nothing frees nothing, and would save looking configured."""
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

	def test_and_nothing_the_engine_cannot_apply_is_ever_on_offer(self):
		"""The rule behind both refusals, stated once.

		If a type is not in `SUPPORTED` it must not be savable, or it becomes a
		live-looking offer the engine skips. This fails the day somebody adds a
		type to the DocType and to neither list.
		"""
		options = frappe.get_meta("Restaurant Promotion").get_field("promotion_type").options
		offered = [line for line in (options or "").splitlines() if line.strip()]

		for promotion_type in offered:
			if promotion_type in promotions.SUPPORTED:
				continue
			with self.subTest(promotion_type=promotion_type), self.assertRaises(frappe.ValidationError):
				self._promotion(
					title=f"RPOS test {promotion_type}",
					promotion_type=promotion_type,
					discount_value=1,
					free_item=ITEM,
				)

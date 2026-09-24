# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""A code that unlocks an offer (`D-248`).

The user asked for it in an influencer's terms: *one code anybody who comes
through this person can use*, **or** *a batch of codes each good once*. Both come
out of `max_uses`, so both are tested here, along with the doors around them —
the offer is off without a code, the code is checked when it is typed, and it is
counted when the money is taken rather than when it is typed.

Refs: FR-11.1, D-163, D-248
"""

import frappe

from restaurant_pos.restaurant_pos.report.coupon_sales import coupon_sales as report
from restaurant_pos.tests.test_order import ITEM
from restaurant_pos.tests.test_payment import PaymentTestBase
from restaurant_pos.utils import coupons
from restaurant_pos.utils import order as orders

PROMOTION = "RPOS test coupon offer"


class CouponTestBase(PaymentTestBase):
	def setUp(self):
		super().setUp()
		self._clear()
		self.promotion = self._offer()

	def tearDown(self):
		self._clear()
		super().tearDown()

	def _clear(self) -> None:
		for code in frappe.get_all(
			"POS Coupon", filters={"coupon_code": ("like", "RPOSTEST%")}, pluck="name"
		):
			frappe.delete_doc("POS Coupon", code, force=True, ignore_permissions=True)
		for name in frappe.get_all("Restaurant Promotion", filters={"title": PROMOTION}, pluck="name"):
			frappe.delete_doc("Restaurant Promotion", name, force=True, ignore_permissions=True)

	def _offer(self, **fields):
		return frappe.get_doc(
			{
				"doctype": "Restaurant Promotion",
				"title": PROMOTION,
				"title_ar": "عرض بكوبون",
				"is_active": 1,
				"is_auto_apply": 1,
				"requires_coupon": 1,
				"promotion_type": "percentage",
				"discount_value": 20,
				"apply_to": "all",
				"item_scope": "all",
			}
			| fields
		).insert(ignore_permissions=True)

	def _coupon(self, code: str = "RPOSTEST1", **fields) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "POS Coupon",
					"coupon_code": code,
					"promotion": self.promotion.name,
					"campaign": "RPOS Test Influencer",
					"is_active": 1,
				}
				| fields
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _bill(self, qty: float = 1):
		order = self._order()
		orders.add_item(order, item=ITEM, qty=qty)
		order.reload()
		return order


class TheOfferIsOffWithoutACode(CouponTestBase):
	def test_a_bill_with_no_coupon_gets_nothing(self):
		self._coupon()

		self.assertEqual(self._bill().promotion_amount, 0.0)

	def test_the_same_bill_with_the_code_gets_it(self):
		self._coupon()
		order = self._bill()

		coupons.attach(order, "RPOSTEST1")
		order.reload()

		self.assertEqual(order.promotion_amount, 5.0, "20% of 25")

	def test_the_code_is_read_however_it_was_typed(self):
		"""A guest reading a code down the phone does not say which letters were capitals."""
		self._coupon()
		order = self._bill()

		coupons.attach(order, "  rpostest1  ")
		order.reload()

		self.assertEqual(order.promotion_amount, 5.0)

	def test_taking_it_back_off_takes_the_offer_with_it(self):
		self._coupon()
		order = self._bill()
		coupons.attach(order, "RPOSTEST1")

		coupons.detach(order)
		order.reload()

		self.assertEqual(order.promotion_amount, 0.0)

	def test_a_code_for_another_offer_does_not_unlock_this_one(self):
		other = self._offer(title="RPOS test coupon offer")
		self._coupon(code="RPOSTEST9", promotion=other.name)
		frappe.db.set_value("Restaurant Promotion", other.name, "is_active", 0)
		order = self._bill()

		with self.assertRaises(frappe.ValidationError):
			coupons.attach(order, "RPOSTEST9")


class WhatTheCodeMustSatisfy(CouponTestBase):
	def test_a_code_nobody_issued_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			coupons.attach(self._bill(), "RPOSNOSUCH")

	def test_a_switched_off_code_is_refused(self):
		self._coupon(is_active=0)

		with self.assertRaises(frappe.ValidationError):
			coupons.attach(self._bill(), "RPOSTEST1")

	def test_a_code_that_has_not_started_is_refused(self):
		self._coupon(valid_from=frappe.utils.add_days(frappe.utils.today(), 3))

		with self.assertRaises(frappe.ValidationError):
			coupons.attach(self._bill(), "RPOSTEST1")

	def test_an_expired_code_is_refused(self):
		self._coupon(valid_to=frappe.utils.add_days(frappe.utils.today(), -1))

		with self.assertRaises(frappe.ValidationError):
			coupons.attach(self._bill(), "RPOSTEST1")

	def test_a_used_up_code_is_refused(self):
		name = self._coupon(max_uses=1)
		frappe.db.set_value("POS Coupon", name, "used", 1)

		with self.assertRaises(frappe.ValidationError):
			coupons.attach(self._bill(), "RPOSTEST1")


class TheTwoShapesTheUserAskedFor(CouponTestBase):
	def test_one_shared_code_serves_everybody(self):
		"""`max_uses = 0` — the influencer reads it out and anyone may use it."""
		name = self._coupon(max_uses=0)

		for _ in range(3):
			order = self._bill()
			coupons.attach(order, "RPOSTEST1")
			self._pay(order.reload())

		self.assertEqual(frappe.db.get_value("POS Coupon", name, "used"), 3)

	def test_a_single_use_code_is_spent_by_the_first_bill(self):
		name = self._coupon(max_uses=1)
		order = self._bill()
		coupons.attach(order, "RPOSTEST1")
		self._pay(order.reload())

		self.assertEqual(frappe.db.get_value("POS Coupon", name, "used"), 1)
		with self.assertRaises(frappe.ValidationError):
			coupons.attach(self._bill(), "RPOSTEST1")


class WhenItIsCounted(CouponTestBase):
	def test_typing_it_does_not_spend_it(self):
		"""A code on a bill that is then cancelled was never used."""
		name = self._coupon()
		order = self._bill()

		coupons.attach(order, "RPOSTEST1")

		self.assertEqual(frappe.db.get_value("POS Coupon", name, "used"), 0)

	def test_paying_spends_it(self):
		name = self._coupon()
		order = self._bill()
		coupons.attach(order, "RPOSTEST1")

		self._pay(order.reload())

		self.assertEqual(frappe.db.get_value("POS Coupon", name, "used"), 1)

	def test_settling_twice_spends_it_once(self):
		"""The offline queue replays a settlement by design (`09` §8)."""
		name = self._coupon()
		order = self._bill()
		coupons.attach(order, "RPOSTEST1")
		self._pay(order.reload())

		coupons.consume(frappe.get_doc("Restaurant Order", order.name))

		self.assertEqual(frappe.db.get_value("POS Coupon", name, "used"), 1)


class TheCampaignCanBeMeasured(CouponTestBase):
	"""`D-248` — a code an influencer hands out is only worth issuing if it can be counted."""

	def _report(self, **extra) -> list[dict]:
		window = {"from_date": frappe.utils.today(), "to_date": frappe.utils.today(), **extra}
		_columns, rows = report.execute(window)
		return rows

	def _sold_with(self, code: str) -> None:
		order = self._bill()
		coupons.attach(order, code)
		self._pay(order.reload())

	def test_a_bill_that_used_a_code_lands_under_its_campaign(self):
		self._coupon(max_uses=0)
		before = [row for row in self._report() if row["campaign"] == "RPOS Test Influencer"]

		self._sold_with("RPOSTEST1")

		mine = [row for row in self._report() if row["campaign"] == "RPOS Test Influencer"]
		self.assertTrue(mine)
		self.assertEqual(mine[0]["bills"] - (before[0]["bills"] if before else 0), 1)

	def test_the_campaign_totals_what_it_gave_away(self):
		self._coupon(max_uses=0)

		self._sold_with("RPOSTEST1")

		mine = next(row for row in self._report() if row["campaign"] == "RPOS Test Influencer")
		self.assertGreater(mine["given"], 0, "the offer behind the code took nothing off")
		self.assertGreater(mine["sales"], mine["given"])

	def test_a_batch_of_codes_reads_as_one_campaign_or_as_many_codes(self):
		self._coupon(code="RPOSTEST1", max_uses=1)
		self._coupon(code="RPOSTEST2", max_uses=1)
		self._sold_with("RPOSTEST1")
		self._sold_with("RPOSTEST2")

		campaigns = [row for row in self._report() if row["campaign"] == "RPOS Test Influencer"]
		codes = [row for row in self._report(group_by_coupon=1) if row["campaign"] == "RPOS Test Influencer"]

		self.assertEqual(len(campaigns), 1, "one influencer, one row")
		self.assertEqual(len(codes), 2, "and the codes behind it when asked")

	def test_a_bill_with_no_code_is_not_in_it(self):
		self._coupon(max_uses=0)
		before = sum(row["bills"] for row in self._report())

		self._pay(self._bill())

		self.assertEqual(sum(row["bills"] for row in self._report()), before)

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
from frappe.tests.utils import FrappeTestCase

from restaurant_pos.api import coupons as issuing
from restaurant_pos.restaurant_pos.report.coupon_sales import coupon_sales as report
from restaurant_pos.tests.test_order import ITEM
from restaurant_pos.tests.test_payment import PaymentTestBase
from restaurant_pos.utils import coupons
from restaurant_pos.utils import order as orders

PROMOTION = "RPOS test coupon offer"
BATCH_PROMOTION = "RPOS batch offer"
UPLOAD_PROMOTION = "RPOS upload offer"


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


class IssuingABatch(FrappeTestCase):
	"""Making the codes in the first place (`D-250`, `D-251`).

	**The generator had no test at all** until the day the button that calls it
	was built — it was written, shipped, and never run by anything. What is
	asserted here is what a batch has to be right about: the codes are the ones
	asked for, a numbered run is a run rather than a set of numbers, and the run
	is refused outright rather than printed with a hole in it.
	"""

	def setUp(self):
		super().setUp()
		self._clear()
		self.promotion = frappe.get_doc(
			{
				"doctype": "Restaurant Promotion",
				"title": BATCH_PROMOTION,
				"title_ar": "عرض الدفعة",
				"is_active": 1,
				"requires_coupon": 1,
				"promotion_type": "percentage",
				"discount_value": 5,
				"apply_to": "all",
				"item_scope": "all",
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		self._clear()
		super().tearDown()

	def _clear(self) -> None:
		offers = frappe.get_all("Restaurant Promotion", filters={"title": BATCH_PROMOTION}, pluck="name")
		for code in frappe.get_all("POS Coupon", filters={"promotion": ("in", offers)}, pluck="name"):
			frappe.delete_doc("POS Coupon", code, force=True, ignore_permissions=True)
		for name in offers:
			frappe.delete_doc("Restaurant Promotion", name, force=True, ignore_permissions=True)

	def _make(self, **fields) -> list[str]:
		return issuing.generate(promotion=self.promotion.name, **fields)["codes"]

	def test_a_drawn_batch_is_as_many_codes_as_were_asked_for(self):
		codes = self._make(count=5)

		self.assertEqual(len(set(codes)), 5)
		self.assertTrue(all(frappe.db.exists("POS Coupon", code) for code in codes))

	def test_drawn_codes_avoid_the_letters_people_misread(self):
		"""`O`/`0` and `1`/`I`/`L` off a card read down a phone."""
		for code in self._make(count=10):
			self.assertFalse(set(code) & set("O0I1L"), code)

	def test_a_numbered_batch_counts_up_from_where_it_was_told_to(self):
		"""The user's own example: 10001, 10002, 10003."""
		codes = self._make(count=3, pattern="sequential", start="10001")

		self.assertEqual(codes, ["10001", "10002", "10003"])

	def test_leading_zeros_are_the_width_that_was_asked_for(self):
		"""Read as an integer, `0001` would come back as `1` and the run breaks."""
		codes = self._make(count=2, pattern="sequential", start="0009")

		self.assertEqual(codes, ["0009", "0010"])

	def test_a_prefix_rides_in_front_of_every_number(self):
		codes = self._make(count=2, pattern="sequential", start="100", prefix="rm-")

		self.assertEqual(codes, ["RM-100", "RM-101"])

	def test_a_run_that_would_collide_is_refused_whole(self):
		"""A gap in a numbered run cannot be told from a card that went missing."""
		self._make(count=2, pattern="sequential", start="500")

		with self.assertRaises(frappe.ValidationError) as refusal:
			self._make(count=3, pattern="sequential", start="499")

		self.assertIn("500", str(refusal.exception))
		self.assertFalse(frappe.db.exists("POS Coupon", "499"), "nothing was written")

	def test_a_start_that_is_not_a_number_is_said_out_loud(self):
		with self.assertRaises(frappe.ValidationError):
			self._make(count=1, pattern="sequential", start="SUMMER")

	def test_a_prefix_that_would_break_a_url_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._make(count=1, pattern="sequential", start="1", prefix="SUMMER 50%")

	def test_a_batch_bigger_than_the_ceiling_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._make(count=issuing.MAX_BATCH + 1)


class TheCodesCanBeUploadedInstead(FrappeTestCase):
	"""A spreadsheet of codes the restaurant already printed (`D-251`).

	**Nothing here is ours.** Frappe ships a Data Import that reads `.csv` and
	`.xlsx`, matches columns by their labels, and reports the rows it could not
	take. Writing a second uploader beside it would be a screen to maintain and
	a second set of error messages for the same job (§5.5). What was missing was
	only permission to reach it.

	So the test does the thing rather than assert the flags: it uploads a file
	and checks that coupons came out of it.
	"""

	def setUp(self):
		super().setUp()
		self.promotion = frappe.get_doc(
			{
				"doctype": "Restaurant Promotion",
				"title": UPLOAD_PROMOTION,
				"title_ar": "عرض الرفع",
				"is_active": 1,
				"requires_coupon": 1,
				"promotion_type": "percentage",
				"discount_value": 5,
				"apply_to": "all",
				"item_scope": "all",
			}
		).insert(ignore_permissions=True)

	def test_a_spreadsheet_of_codes_becomes_coupons(self):
		from frappe.core.doctype.data_import.importer import Importer

		sheet = frappe.get_doc(
			doctype="File",
			file_name="rpos_coupon_upload.csv",
			is_private=1,
			content="\n".join(
				(
					"Coupon Code,Promotion,Campaign,Maximum Uses",
					f"RPOSUP1,{self.promotion.name},RPOS Upload,1",
					f"RPOSUP2,{self.promotion.name},RPOS Upload,1",
				)
			),
		).save(ignore_permissions=True)

		upload = frappe.get_doc(
			{
				"doctype": "Data Import",
				"reference_doctype": "POS Coupon",
				"import_type": "Insert New Records",
				"import_file": sheet.file_url,
			}
		).insert(ignore_permissions=True)

		# Driven directly rather than through `start_import`, which swallows a
		# failure into a status field — a test that reads "Error" as silence is
		# a test that passes while the feature is broken.
		Importer("POS Coupon", data_import=upload).import_data()

		for code in ("RPOSUP1", "RPOSUP2"):
			self.assertTrue(frappe.db.exists("POS Coupon", code), f"{code} was not imported")
			self.assertEqual(frappe.db.get_value("POS Coupon", code, "campaign"), "RPOS Upload")

	def test_the_list_offers_frappes_own_import(self):
		"""**Two flags, and the menu entry needs both** (`D-251`).

		`allow_import` alone leaves the manager with no way in — the Import item
		is drawn from the role's own `import` right — and the right alone fails
		at the Data Import document's validation. Nothing warns about either
		half, so both are asserted rather than remembered.
		"""
		meta = frappe.get_meta("POS Coupon")

		self.assertTrue(meta.allow_import)

		importers = {perm.role for perm in meta.permissions if perm.get("import")}
		self.assertIn("Restaurant Manager", importers)

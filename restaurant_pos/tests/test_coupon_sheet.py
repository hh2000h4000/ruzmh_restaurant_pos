# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The A4 sheet of coupon cards (`D-250`).

The codes had nowhere to be printed, so they were being read off a list — which
is not a thing you hand a guest. What is asserted here is what a card has to be
right about: **the QR holds the bare code** (a till scanner types what it reads
into the coupon box, so a URL in there would be typed into the coupon box), the
card tells the truth about **how long it is good for** even when the coupon
itself carries no dates, and ten cards to a page means the eleventh starts a
second page rather than being dropped.

Refs: FR-11.1, D-250
"""

import json
import os

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import set_request
from frappe.website.serve import get_response_content

from restaurant_pos.utils.barcodes import qr_data_uri
from restaurant_pos.www import rpos_card_sheet as sheet

PROMOTION = "RPOS sheet offer"
PREFIX = "RPOSSHEET"


class SheetTestBase(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self._clear()
		self.promotion = frappe.get_doc(
			{
				"doctype": "Restaurant Promotion",
				"title": PROMOTION,
				"title_ar": "عرض الورقة",
				"is_active": 1,
				"requires_coupon": 1,
				"promotion_type": "percentage",
				"discount_value": 10,
				"apply_to": "all",
				"item_scope": "all",
				"valid_from": "2026-01-01",
				"valid_to": "2026-12-31",
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.form_dict.pop("names", None)
		frappe.form_dict.pop("kind", None)
		frappe.local.request = None
		self._clear()
		super().tearDown()

	def _clear(self) -> None:
		for code in frappe.get_all("POS Coupon", filters={"name": ("like", f"{PREFIX}%")}, pluck="name"):
			frappe.delete_doc("POS Coupon", code, force=True, ignore_permissions=True)
		for name in frappe.get_all("Restaurant Promotion", filters={"title": PROMOTION}, pluck="name"):
			frappe.delete_doc("Restaurant Promotion", name, force=True, ignore_permissions=True)

	def _coupon(self, suffix: str = "1", **fields) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "POS Coupon",
					"coupon_code": f"{PREFIX}{suffix}",
					"promotion": self.promotion.name,
					"campaign": "RPOS Test Influencer",
					"max_uses": 1,
					"is_active": 1,
				}
				| fields
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _context(self, names: list[str]) -> frappe._dict:
		frappe.form_dict.names = json.dumps(names)
		frappe.form_dict.kind = "coupon"
		return sheet.get_context(frappe._dict())

	def _html(self, names: list[str]) -> str:
		context = self._context(names)
		# Joined by hand: `get_app_path` scrubs its parts, and the hyphen in the
		# page's name would come back as an underscore and find nothing.
		page = os.path.join(frappe.get_app_path("restaurant_pos"), "www", "rpos-card-sheet.html")
		source = frappe.read_file(page)
		self.assertTrue(source, f"no template at {page}")
		return frappe.render_template(source, context)


class TestWhatIsOnACard(SheetTestBase):
	def test_the_qr_holds_the_code_and_nothing_else(self):
		"""A wedge scanner types what it reads into the field that has focus."""
		name = self._coupon()

		(card,) = self._context([name]).cards

		self.assertEqual(card["qr"], qr_data_uri(f"{PREFIX}1"))

	def test_the_offer_is_named_in_arabic(self):
		name = self._coupon()

		(card,) = self._context([name]).cards

		self.assertEqual(card["title"], "عرض الورقة")

	def test_the_offers_dates_show_when_the_coupon_carries_none(self):
		"""Blank on the coupon means "whatever the offer says", so say it."""
		name = self._coupon()

		(card,) = self._context([name]).cards

		self.assertIn("2026", card["lines"][1])
		self.assertIn("12", card["lines"][1])

	def test_the_coupons_own_dates_win(self):
		name = self._coupon(valid_to="2026-03-05")

		(card,) = self._context([name]).cards

		self.assertIn("05", card["lines"][1])
		self.assertNotIn("31", card["lines"][1])

	def test_only_a_single_use_code_says_so(self):
		once = self._coupon("1", max_uses=1)
		shared = self._coupon("2", max_uses=0)

		cards = {card["code"]: card for card in self._context([once, shared]).cards}

		# Compared against each other rather than against a sentence: the wording
		# is translated, and a test that matches the Arabic passes only on a site
		# running in Arabic.
		extra = set(cards[f"{PREFIX}1"]["lines"]) - set(cards[f"{PREFIX}2"]["lines"])

		self.assertTrue(extra, "a single-use card says so, and a shared one has nothing to say")


class TestTheSheet(SheetTestBase):
	def test_nothing_selected_is_refused_rather_than_printed_blank(self):
		frappe.form_dict.names = json.dumps([])

		with self.assertRaises(frappe.ValidationError):
			sheet.get_context(frappe._dict())

	def test_the_eleventh_card_starts_a_second_page(self):
		"""Ten to a page — the eleventh must not be silently dropped."""
		names = [self._coupon(str(index)) for index in range(11)]

		html = self._html(names)

		self.assertEqual(html.count('class="card"'), 11)
		self.assertEqual(html.count('class="sheet"'), 2)

	def test_every_code_is_printed_where_a_person_can_read_it(self):
		names = [self._coupon(str(index)) for index in range(3)]

		html = self._html(names)

		for index in range(3):
			self.assertIn(f"{PREFIX}{index}", html)

	def test_the_route_reaches_this_page(self):
		"""Frappe pairs a page with its controller by the **underscored** name.

		Get that pairing wrong and nothing says so: the page still renders, wrapped
		in the website theme, with no cards on it — because `get_context` was never
		called. So the route is fetched here rather than the template rendered by
		hand.
		"""
		frappe.form_dict.names = json.dumps([self._coupon()])
		frappe.form_dict.kind = "coupon"
		set_request(method="GET", path="/rpos-card-sheet")

		html = get_response_content("/rpos-card-sheet")

		self.assertIn(f"{PREFIX}1", html)
		self.assertIn("@page", html)
		# Nothing left unrendered — the page direction is set from the controller
		# too, and an unpaired controller leaves that sitting in the markup.
		self.assertNotIn("{{", html)

	def test_it_is_a_standalone_page_not_a_website_one(self):
		"""Frappe wraps a www page in the site theme unless it closes its own body."""
		html = self._html([self._coupon()])

		self.assertIn("</body>", html)
		self.assertIn("@page", html)

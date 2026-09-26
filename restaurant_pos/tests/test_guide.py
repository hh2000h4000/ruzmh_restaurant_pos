# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The user guide, opened from the office (`D-262`).

The guide was read on GitHub, and the repository is private: the customer it is
written for got a 404. It is served now by the system itself, and what is held
here is what that promise rests on — every page renders with its pictures and
its links pointing at this site, nothing outside the guide's folder can be
asked for by name, and the office's help menu carries the way in.

**And the chain holds.** Pages were added over two weeks with «السابق/التالي»
written by hand, and sixteen of them had none. Every footer is checked against
the README's list, so a page added later without one fails here, by name.

Refs: D-222, D-262
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import set_request
from frappe.website.serve import get_response_content

from restaurant_pos.setup.install import GUIDE_ROUTE, add_guide_to_help_menu
from restaurant_pos.www import rpos_guide as guide


class TheChain(FrappeTestCase):
	def test_every_page_in_the_list_exists(self):
		for stem, _title in guide.pages():
			self.assertTrue((guide.GUIDE / f"{stem}.md").is_file(), stem)

	def test_every_page_is_in_the_list(self):
		listed = {stem for stem, _title in guide.pages()}
		on_disk = {path.stem for path in guide.GUIDE.glob("*.md")} - {"README"}
		self.assertEqual(on_disk - listed, set(), "pages nobody can reach from the README")

	def test_every_footer_follows_the_list(self):
		order = guide.pages()
		for i, (stem, _title) in enumerate(order):
			text = (guide.GUIDE / f"{stem}.md").read_text(encoding="utf-8")
			with self.subTest(page=stem):
				if i > 0:
					before, title = order[i - 1]
					self.assertIn(f"السابق: [{title}]({before}.md)", text)
				if i < len(order) - 1:
					after, title = order[i + 1]
					self.assertIn(f"التالي: [{title}]({after}.md)", text)
				self.assertIn("الرجوع لـ[صفحة البداية](README.md)", text)


class ThePage(FrappeTestCase):
	def tearDown(self):
		frappe.form_dict.pop("page", None)
		frappe.local.request = None
		frappe.set_user("Administrator")
		super().tearDown()

	def _render(self, page: str | None = None) -> str:
		path = f"{GUIDE_ROUTE}/{page}" if page else GUIDE_ROUTE
		set_request(method="GET", path=path)
		return get_response_content(path)

	def test_a_page_renders_with_its_pictures_and_this_sites_links(self):
		html = self._render("coupons")

		self.assertIn("/assets/restaurant_pos/guide/images/coupon-1.png", html)
		self.assertIn(f'href="{GUIDE_ROUTE}/gift-cards"', html)
		self.assertIn(f'href="{GUIDE_ROUTE}"', html)
		# Nothing left in GitHub's shape, and nothing left unrendered.
		self.assertNotIn(".md)", html)
		self.assertNotIn('.md"', html)
		self.assertNotIn("{{", html)

	def test_the_guide_is_arabic_and_right_to_left_for_an_english_account(self):
		"""`D-222` — the pages are Arabic only; an English office mirrored their tables."""
		frappe.local.lang = "en"
		self.addCleanup(setattr, frappe.local, "lang", "ar")

		html = self._render("gift-card-accounting")

		self.assertIn('dir="rtl"', html)
		self.assertIn("دليل نقاط البيع", html)

	def test_the_start_page_is_the_readme(self):
		html = self._render()

		self.assertIn(f'href="{GUIDE_ROUTE}/add-branch"', html)

	def test_a_name_outside_the_guide_is_not_a_page(self):
		for page in ("../hooks", "README.md", "no-such-page"):
			with self.subTest(page=page), self.assertRaises(frappe.PageDoesNotExistError):
				guide._source(page)

	def test_a_visitor_who_is_not_signed_in_is_sent_to_sign_in(self):
		frappe.set_user("Guest")
		set_request(method="GET", path=GUIDE_ROUTE)

		with self.assertRaises(frappe.Redirect):
			guide.get_context(frappe._dict())
		self.assertTrue(frappe.local.flags.redirect_location.startswith("/login"))


class TheHelpMenu(FrappeTestCase):
	def _rows(self) -> list:
		return [row for row in frappe.get_single("Navbar Settings").help_dropdown if row.route == GUIDE_ROUTE]

	def test_the_guide_is_in_the_help_menu_once(self):
		add_guide_to_help_menu()
		add_guide_to_help_menu()

		self.assertEqual(len(self._rows()), 1)

	def test_a_label_the_manager_renamed_is_left_alone(self):
		add_guide_to_help_menu()
		navbar = frappe.get_single("Navbar Settings")
		row = next(row for row in navbar.help_dropdown if row.route == GUIDE_ROUTE)
		row.item_label = "Our handbook"
		navbar.save(ignore_permissions=True)

		add_guide_to_help_menu()

		self.assertEqual([row.item_label for row in self._rows()], ["Our handbook"])

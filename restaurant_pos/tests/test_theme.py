# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The brand colours a terminal renders with (`D-198`).

The resolution order is the whole feature: a chain brands each branch, a single
restaurant sets one theme and forgets it, and **a terminal is never unstyled**
(`FR-15.2`, `FR-15.6`). So the claims are made on the payload the device
caches, not on a helper's return value.

And readability is a rule, not a taste (`FR-15.3`): a pair below 4.5:1 is
refused on save, because a cashier reads this screen under restaurant lighting.

Refs: FR-15.1..FR-15.6, D-014, D-198
"""

import frappe

from restaurant_pos.tests.test_order import OrderTestBase
from restaurant_pos.utils import theme as theme_service

#: A readable theme: the house look with one colour changed, so a test can tell
#: which theme answered.
TERMINAL_GREEN = "#14532D"
BRANCH_BLUE = "#1E3A8A"
HOUSE_DEFAULT = "#4C1D95"


class TestTheThemeATerminalRendersWith(OrderTestBase):
	def setUp(self):
		frappe.local.rpos_permission_cache = {}
		# A terminal has no branch column: it reaches one through its section.
		section = frappe.db.get_value("POS Profile", self.profile, "restaurant_section")
		self.branch = frappe.db.get_value("Restaurant Section", section, "branch") if section else None
		# Nothing from a previous test may decide this one's answer.
		self._clear("POS Profile", self.profile)
		self._clear("Branch", self.branch)
		for name in frappe.get_all("RPOS Theme", filters={"is_default": 1}, pluck="name"):
			self._set("RPOS Theme", name, "is_default", 0)

	def _set(self, doctype: str, name: str, field: str, value) -> None:
		"""Set a field and put the old value back when the test ends."""
		before = frappe.db.get_value(doctype, name, field)
		frappe.db.set_value(doctype, name, field, value)
		frappe.clear_document_cache(doctype, name)
		self.addCleanup(frappe.clear_document_cache, doctype, name)
		self.addCleanup(frappe.db.set_value, doctype, name, field, before)

	def _clear(self, doctype: str, name: str | None) -> None:
		if name:
			self._set(doctype, name, "rpos_theme", None)

	def _theme(self, primary: str, **overrides) -> str:
		theme = frappe.get_doc(
			{
				"doctype": "RPOS Theme",
				"title": f"RPOS Test {frappe.generate_hash(length=6)}",
				"title_ar": "ثيم اختبار",
				"primary_color": primary,
				"primary_contrast": "#FFFFFF",
				"secondary_color": "#2F6D61",
				"secondary_contrast": "#F6F4F0",
				"surface_color": "#FFFFFF",
				"background_color": "#F3F1ED",
				"text_color": "#14171A",
				**overrides,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "RPOS Theme", theme.name, force=True, ignore_permissions=True)
		return theme.name

	def _rendered(self) -> dict:
		from restaurant_pos.api import session

		return session.load_pos_session(self.profile)["theme"]

	def test_the_terminals_own_theme_wins(self):
		self._theme(HOUSE_DEFAULT, is_default=1)
		self._set("Branch", self.branch, "rpos_theme", self._theme(BRANCH_BLUE))
		self._set("POS Profile", self.profile, "rpos_theme", self._theme(TERMINAL_GREEN))

		self.assertEqual(self._rendered()["primary"], TERMINAL_GREEN)

	def test_without_one_the_branch_answers(self):
		self._theme(HOUSE_DEFAULT, is_default=1)
		self._set("Branch", self.branch, "rpos_theme", self._theme(BRANCH_BLUE))

		self.assertEqual(self._rendered()["primary"], BRANCH_BLUE)

	def test_and_without_either_the_default_theme_does(self):
		self._theme(HOUSE_DEFAULT, is_default=1)

		self.assertEqual(self._rendered()["primary"], HOUSE_DEFAULT)

	def test_a_theme_switched_off_is_stepped_over_not_rendered(self):
		"""Switching one off must not leave its terminals with no colours at all."""
		self._theme(HOUSE_DEFAULT, is_default=1)
		self._set("POS Profile", self.profile, "rpos_theme", self._theme(TERMINAL_GREEN, is_active=0))

		self.assertEqual(self._rendered()["primary"], HOUSE_DEFAULT)

	def test_with_no_theme_at_all_the_till_still_has_colours(self):
		"""`FR-15.6` — never unstyled, on a fresh site or an offline start."""
		self.assertEqual(self._rendered()["primary"], theme_service.HOUSE["primary"])

	def test_a_token_left_empty_falls_back_to_the_house_look(self):
		"""A colour added to the theme later is NULL on every record that predates it."""
		name = self._theme(TERMINAL_GREEN)
		self._set("POS Profile", self.profile, "rpos_theme", name)
		self._set("RPOS Theme", name, "surface_color", None)

		self.assertEqual(self._rendered()["surface"], theme_service.HOUSE["surface"])

	def test_the_logo_travels_with_the_colours(self):
		"""The receipt and the customer display read it (`FR-13.1`, `FR-15.1`)."""
		self._set(
			"POS Profile",
			self.profile,
			"rpos_theme",
			self._theme(TERMINAL_GREEN, brand_logo="/files/rpos-logo.png"),
		)

		self.assertEqual(self._rendered()["brand_logo"], "/files/rpos-logo.png")


class TestWhatAThemeIsAllowedToLookLike(OrderTestBase):
	"""Rules enforced on save, so no unreadable theme ever reaches a terminal."""

	def _readable(self, **overrides) -> dict:
		return {
			"doctype": "RPOS Theme",
			"title": f"RPOS Test {frappe.generate_hash(length=6)}",
			"title_ar": "ثيم اختبار",
			"primary_color": "#1F4B43",
			"primary_contrast": "#F6F4F0",
			"secondary_color": "#2F6D61",
			"secondary_contrast": "#F6F4F0",
			"surface_color": "#FFFFFF",
			"background_color": "#F3F1ED",
			"text_color": "#14171A",
			**overrides,
		}

	def _save(self, **overrides):
		doc = frappe.get_doc(self._readable(**overrides)).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "RPOS Theme", doc.name, force=True, ignore_permissions=True)
		return doc

	def test_grey_text_on_a_white_ground_is_refused(self):
		"""4.5:1 is what a cashier needs under restaurant lighting, not a preference."""
		with self.assertRaises(frappe.ValidationError):
			self._save(background_color="#FFFFFF", text_color="#CCCCCC")

	def test_white_on_the_house_green_is_allowed(self):
		self.assertTrue(self._save().name)

	def test_the_default_mark_moves_rather_than_doubles(self):
		"""`FR-15.2`'s last step must never find two answers."""
		first = self._save(is_default=1)
		second = self._save(is_default=1)

		self.assertEqual(frappe.db.get_value("RPOS Theme", first.name, "is_default"), 0)
		self.assertEqual(frappe.db.get_value("RPOS Theme", second.name, "is_default"), 1)

	def test_a_private_logo_is_refused(self):
		"""A cashier may not fetch it, so every terminal would show a broken logo."""
		with self.assertRaises(frappe.ValidationError):
			self._save(brand_logo="/private/files/rpos-logo.png")

	def test_the_contrast_of_black_on_white_is_the_known_ratio(self):
		"""The arithmetic itself, against WCAG's published figure."""
		self.assertAlmostEqual(theme_service.contrast("#000000", "#FFFFFF"), 21.0, places=1)
		self.assertAlmostEqual(theme_service.contrast("#FFFFFF", "#FFFFFF"), 1.0, places=1)

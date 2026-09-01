# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The published SPA page must stay per-session.

Refs: D-030, D-031
"""

import frappe
from frappe.tests.utils import FrappeTestCase

ROUTE = "restaurant-pos"


class TestCsrfToken(FrappeTestCase):
	"""The page can ask for a token when its own copy is empty (D-031)."""

	def test_a_signed_in_session_gets_its_own_token(self):
		"""The test runner has no HTTP session, so one is put in place first."""
		from restaurant_pos.api import session

		before = frappe.session.data.get("csrf_token")
		frappe.session.data.csrf_token = "rpos-test-token"
		try:
			self.assertEqual(session.csrf_token()["csrf_token"], "rpos-test-token")
		finally:
			frappe.session.data.csrf_token = before

	def test_a_session_without_one_is_given_one(self):
		"""D-103 — the case that stopped a till from opening a shift.

		This test used to assert the opposite: that a session with no token was
		refused, on the reasoning that Frappe issues one when a session starts.
		It does — when a **page** is rendered. A session built by
		`login_manager.login_as` for a PIN sign-in renders nothing, so the
		cashier had a perfectly good session with no token, and the first thing
		they touched was refused with an instruction to sign out and sign in
		again: the one action guaranteed not to help.
		"""
		from restaurant_pos.api import session

		before = frappe.session.data.get("csrf_token")
		frappe.session.data.csrf_token = None
		try:
			token = session.csrf_token()["csrf_token"]

			self.assertTrue(token)
			self.assertEqual(frappe.session.data.csrf_token, token, "it must stick to the session")
		finally:
			frappe.session.data.csrf_token = before

	def test_a_guest_gets_nothing(self):
		from restaurant_pos.api import session

		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				session.csrf_token()
		finally:
			frappe.set_user("Administrator")


class TestPublishedPage(FrappeTestCase):
	def _renderer(self):
		from frappe.website.page_renderers.template_page import TemplatePage

		page = TemplatePage(path=ROUTE)
		if not page.can_render():
			self.skipTest("the frontend has not been built on this bench")
		return page

	def test_the_page_carries_a_csrf_token(self):
		"""Without it every POST is refused with a bare 400 (D-030)."""
		page = self._renderer()
		self.assertIn("window.csrf_token", page.get_html())

	def test_the_page_is_never_cached(self):
		"""D-031 — the cache key is the path alone, with no user in it.

		A cached page hands whoever loaded it first their CSRF token, and every
		other cashier inherits it. If that first visitor was signed out the
		token is empty and no till can write anything.
		"""
		page = self._renderer()
		frappe.cache.hdel("website_page", ROUTE)

		page.get_html()

		self.assertFalse(
			frappe.cache.hget("website_page", ROUTE),
			"the POS page was stored in the website cache — check www/restaurant-pos.py",
		)

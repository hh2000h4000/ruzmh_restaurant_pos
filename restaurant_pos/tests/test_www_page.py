# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The published SPA page must stay per-session.

Refs: D-030, D-031
"""

import frappe
from frappe.tests.utils import FrappeTestCase

ROUTE = "restaurant-pos"


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

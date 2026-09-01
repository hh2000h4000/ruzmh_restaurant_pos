# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The demo clean-up refuses to run where the residue is not residue.

`RPOS-TEST-BURGER`, `RPOS Test Grill` and the rest are smoke-test leftovers on
the demo site and **the suite's own fixtures** on the test site. One function
deleting by name pattern cannot tell them apart, so it asks the site instead.

This test runs on the very site the guard protects, which is the only place the
question is real: if the guard ever stops working, this file's own fixtures are
the first thing to go.

Refs: D-087
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant_pos.setup import demo_cleanup


class TestTheGuard(FrappeTestCase):
	def test_it_refuses_on_the_site_the_suite_runs_against(self):
		self.assertTrue(
			frappe.db.exists("POS Profile", demo_cleanup.TEST_SITE_MARKER),
			"the marker this guard keys on is missing; the guard cannot work",
		)

		with self.assertRaises(frappe.ValidationError):
			demo_cleanup.clean()

	def test_the_fixtures_it_would_have_deleted_are_still_here(self):
		"""Named explicitly, so a broken guard fails loudly rather than oddly.

		Without this, a guard that stopped working would surface as dozens of
		unrelated tests failing on missing items, and the cause would take a
		while to find.
		"""
		try:
			demo_cleanup.clean()
		except frappe.ValidationError:
			pass

		self.assertTrue(frappe.db.exists("Item", "RPOS-TEST-BURGER"))
		self.assertTrue(frappe.db.exists("Production Center", {"title": "RPOS Test Grill"}))

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The suite refuses to run on a site somebody uses (`D-255`).

**Written after it happened.** Two runs went out naming the demo site instead of
the test site, and thirty-two menu prices were deleted before a line of output
appeared — ERPNext's own `before_tests` empties `Item Price` outright.

What is asserted is the refusal itself, since the hook that carries it is the
one thing standing between a mistyped site name and somebody's data.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant_pos.setup import test_fixtures


class TestWhichSitesTheSuiteMayRuin(FrappeTestCase):
	def test_the_site_it_is_running_on_is_allowed(self):
		"""If this ever fails, the suite is running somewhere it should not be."""
		test_fixtures.refuse_on_a_site_somebody_uses()

	def test_a_site_that_is_not_disposable_is_refused_by_name(self):
		with patch.object(frappe.local, "site", "rpos.localhost"):
			with self.assertRaises(frappe.ValidationError) as refusal:
				test_fixtures.refuse_on_a_site_somebody_uses()

		self.assertIn("rpos.localhost", str(refusal.exception))

	def test_a_site_that_says_it_is_disposable_is_allowed(self):
		"""The way out for anybody whose test site is not named `test.localhost`."""
		with patch.object(frappe.local, "site", "someone-elses-test.localhost"):
			with patch.dict(frappe.conf, {"rpos_disposable_site": 1}):
				test_fixtures.refuse_on_a_site_somebody_uses()

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The terminals a user may bind a device to.

Refs: D-035, 07 §2, BR-003
"""

import frappe

from restaurant_pos.api import session
from restaurant_pos.tests.test_order import OrderTestBase


class TestListPosProfiles(OrderTestBase):
	def _names(self):
		return {row["name"] for row in session.list_pos_profiles()}

	def test_it_lists_the_terminal_this_site_has(self):
		self.assertIn(self.profile, self._names())

	def test_a_row_carries_what_the_button_shows(self):
		row = next(entry for entry in session.list_pos_profiles() if entry["name"] == self.profile)

		for key in ("name", "company", "branch", "section_title", "section_title_ar"):
			self.assertIn(key, row)

	def test_a_disabled_terminal_is_not_offered(self):
		frappe.db.set_value("POS Profile", self.profile, "disabled", 1)
		try:
			self.assertNotIn(self.profile, self._names())
		finally:
			frappe.db.set_value("POS Profile", self.profile, "disabled", 0)

	def test_a_terminal_restricted_to_other_users_is_not_offered(self):
		"""`applicable_for_users` is ERPNext's own restriction; honour it."""
		profile = frappe.get_doc("POS Profile", self.profile)
		original = list(profile.applicable_for_users)

		profile.applicable_for_users = []
		profile.append("applicable_for_users", {"user": "Administrator"})
		profile.save(ignore_permissions=True)

		try:
			frappe.set_user("Guest")
			self.assertNotIn(self.profile, self._names())
		finally:
			frappe.set_user("Administrator")
			profile.reload()
			profile.applicable_for_users = []
			for row in original:
				profile.append("applicable_for_users", {"user": row.user})
			profile.save(ignore_permissions=True)

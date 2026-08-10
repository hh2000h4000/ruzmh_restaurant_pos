# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Branch scoping.

Refs: 08_Security.md §1 layer 2, 02_backend_rules.md
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant_pos.utils.permissions import validate_branch_access

BRANCH = "Riyadh"
CASHIER = "rpos_branch_cashier@example.com"


def _cashier() -> str:
	if not frappe.db.exists("User", CASHIER):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": CASHIER,
				"first_name": "RPOS Branch Cashier",
				"send_welcome_email": 0,
				"roles": [{"role": "POS Cashier"}],
			}
		).insert(ignore_permissions=True)
	return CASHIER


class TestBranchAccess(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.cashier = _cashier()
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in frappe.get_all(
			"User Permission", filters={"user": CASHIER, "allow": "Branch"}, pluck="name"
		):
			frappe.delete_doc("User Permission", name, force=True, ignore_permissions=True)
		frappe.db.commit()

	def test_an_unrestricted_cashier_may_work_in_any_branch(self):
		"""A single-branch restaurant configures nothing and everything works.

		The previous implementation asked whether the cashier could read the
		Branch DocType, which no POS role can — so every call failed.
		"""
		frappe.set_user(self.cashier)
		validate_branch_access(BRANCH)

	def test_a_restricted_cashier_is_held_to_their_branch(self):
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": CASHIER,
				"allow": "Branch",
				"for_value": BRANCH,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

		frappe.set_user(self.cashier)
		validate_branch_access(BRANCH)

		with self.assertRaises(frappe.PermissionError):
			validate_branch_access("_RPOS Somewhere Else")

	def test_the_administrator_is_never_restricted(self):
		validate_branch_access("_RPOS Somewhere Else")

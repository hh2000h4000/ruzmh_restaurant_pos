# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Who may use the till at all (`D-208`).

`validate_branch_access` asked only the branch question, and a single-branch
restaurant restricts nobody — so every endpoint that stopped there was open to
any signed-in account. The customer endpoints did not even stop there. A till
role is now the price of entry, with `Administrator` the one exception; desk
forms are guarded by their own DocType permission instead.

The print agent is not tested here: it never passes this gate, and
`test_printing.TestTheAgentSeam` claims and reports as its own role-less user.

Refs: CLAUDE.md §4, 08_Security.md §1, D-208
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant_pos.api import customer as customer_api
from restaurant_pos.api import routing as routing_api
from restaurant_pos.api import table as table_api
from restaurant_pos.tests.test_order import BRANCH
from restaurant_pos.tests.test_routing_editor import GRILL
from restaurant_pos.utils import permissions as perms

#: A desk login with no till role — the accountant, say.
NOBODY = "rpos_gate_desk_only@example.com"
#: A System Manager with no till role. Refused: configuring is not selling.
SYSTEM_MANAGER = "rpos_gate_system_manager@example.com"
CASHIER = "rpos_gate_cashier@example.com"


def _user(email: str, roles: list[str]) -> str:
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"roles": [{"role": role} for role in roles],
			}
		).insert(ignore_permissions=True)
	return email


class TestTheTillNeedsATillRole(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_user(NOBODY, ["Accounts User"])
		_user(SYSTEM_MANAGER, ["System Manager"])
		_user(CASHIER, ["POS Cashier"])
		cls.section = frappe.db.get_value("Restaurant Section", {"branch": BRANCH}, "name")
		cls.grill = frappe.db.get_value("Production Center", {"title": GRILL, "branch": BRANCH}, "name")
		frappe.db.commit()

	def setUp(self):
		super().setUp()
		frappe.local.rpos_permission_cache = {}

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.rpos_permission_cache = {}
		super().tearDown()

	def _as(self, user: str):
		frappe.set_user(user)
		frappe.local.rpos_permission_cache = {}

	# ------------------------------------------------ an endpoint that only asked the branch

	def test_a_login_with_no_till_role_is_refused_where_only_the_branch_was_asked(self):
		self._as(NOBODY)

		with self.assertRaises(frappe.PermissionError):
			table_api.get_floor_plan(self.section)

	def test_a_system_manager_with_no_till_role_is_refused_too(self):
		"""The accountant holds System Manager; exempting it would leave the
		example this gate was written for exactly where it was."""
		self._as(SYSTEM_MANAGER)

		with self.assertRaises(frappe.PermissionError):
			table_api.get_floor_plan(self.section)

	def test_a_cashier_still_gets_the_floor(self):
		"""The other side of the line — or the gate is a wall."""
		self._as(CASHIER)

		self.assertIn("tables", table_api.get_floor_plan(self.section))

	def test_the_administrator_passes(self):
		self.assertTrue(perms.is_pos_user("Administrator"))
		table_api.get_floor_plan(self.section)

	# ------------------------------------------------ customers, which named no branch at all

	def test_customers_phone_numbers_are_not_readable_without_a_till_role(self):
		self._as(NOBODY)

		with self.assertRaises(frappe.PermissionError):
			customer_api.search(phone="0500000000")
		with self.assertRaises(frappe.PermissionError):
			customer_api.get(frappe.db.get_value("Customer", {}, "name") or "anyone")

	def test_a_customer_cannot_be_made_without_a_till_role(self):
		self._as(SYSTEM_MANAGER)
		before = frappe.db.count("Customer")

		with self.assertRaises(frappe.PermissionError):
			customer_api.create(phone="0500000001", customer_name="RPOS Gate Probe")

		self.assertEqual(frappe.db.count("Customer"), before)

	def test_a_cashier_can_still_look_a_customer_up(self):
		self._as(CASHIER)

		self.assertIsInstance(customer_api.search(phone="0500000000"), list)

	# ------------------------------------------------ kitchen routing: the form's own permission

	def test_a_cashier_cannot_rewire_the_kitchen(self):
		"""A till role is not enough: the Production Center form is written by
		managers, and the endpoint follows the form."""
		self._as(CASHIER)
		before = frappe.db.count("POS Printer Routing Rule", {"production_center": self.grill})

		with self.assertRaises(frappe.PermissionError):
			routing_api.set_station_groups(self.grill, [])

		self.assertEqual(
			frappe.db.count("POS Printer Routing Rule", {"production_center": self.grill}), before
		)

	def test_a_login_with_no_role_at_all_cannot_rewire_it_either(self):
		self._as(NOBODY)

		with self.assertRaises(frappe.PermissionError):
			routing_api.set_station_groups(self.grill, [])

	def test_a_system_manager_configures_the_kitchen_from_the_desk_without_a_till_role(self):
		"""The desk is not the till: the form's permission decides, not the gate."""
		self._as(SYSTEM_MANAGER)

		self.assertEqual(routing_api.station_groups(self.grill)["production_center"], self.grill)

	def test_reading_the_routing_follows_the_form_s_read_permission(self):
		self._as(NOBODY)

		with self.assertRaises(frappe.PermissionError):
			routing_api.station_groups(self.grill)

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""One till, every hall.

A restaurant with a men's hall and a family hall usually runs one terminal at
the door for both. Tying a table to the terminal's own section forced a second
terminal on it for no reason, so the check is the **branch** and the hall comes
from the table.

Refs: D-040, BR-064
"""

import frappe

from restaurant_pos.setup import test_fixtures
from restaurant_pos.tests.test_order import BRANCH, OrderTestBase
from restaurant_pos.utils import order as service

OTHER_SECTION = "RPOS Test Family Hall"
OTHER_TABLE = "RPOS Test Family Table"


class TestTablesOutsideTheTerminalSection(OrderTestBase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		if not frappe.db.exists("Restaurant Section", {"title": OTHER_SECTION}):
			frappe.get_doc(
				{
					"doctype": "Restaurant Section",
					"title": OTHER_SECTION,
					"title_ar": "صالة العوائل",
					"branch": BRANCH,
					# A family hall is dining, served its own way — the same
					# `section_type` as any other dining room.
					"section_type": "dine_in",
					"has_tables": 1,
					"is_active": 1,
				}
			).insert(ignore_permissions=True)

		cls.other_section = frappe.db.get_value("Restaurant Section", {"title": OTHER_SECTION}, "name")

		if not frappe.db.exists("Restaurant Table", {"table_number": OTHER_TABLE}):
			frappe.get_doc(
				{
					"doctype": "Restaurant Table",
					"table_number": OTHER_TABLE,
					"section": cls.other_section,
					"capacity": 6,
					"status": "available",
					"is_active": 1,
				}
			).insert(ignore_permissions=True)

		cls.other_table = frappe.db.get_value("Restaurant Table", {"table_number": OTHER_TABLE}, "name")
		frappe.db.commit()

	def setUp(self):
		frappe.db.set_value(
			"Restaurant Table", self.other_table, {"status": "available", "current_order": None}
		)

	def test_a_table_in_another_hall_can_be_seated(self):
		"""The terminal sits in one hall and seats a table in the other."""
		self.assertNotEqual(self.section, self.other_section)

		order = self._order(order_type=self.dine_in, table=self.other_table, cover_count=4)

		self.assertEqual(order.table, self.other_table)
		self.assertEqual(frappe.db.get_value("Restaurant Table", self.other_table, "status"), "occupied")

	def test_the_order_belongs_to_the_table_s_hall_not_the_terminal_s(self):
		"""The section on the order is what tells the kitchen where to carry it."""
		order = self._order(order_type=self.dine_in, table=self.other_table, cover_count=2)

		self.assertEqual(order.section, self.other_section)

	def test_an_order_with_no_table_keeps_the_terminal_s_hall(self):
		order = self._order()
		self.assertEqual(order.section, self.section)

	def test_a_table_in_another_branch_is_still_refused(self):
		"""The branch is the boundary that stayed (BR-064)."""
		other_branch = frappe.db.get_value("Branch", {"name": ("!=", BRANCH)}, "name")
		if not other_branch:
			self.skipTest("the site has only one branch")

		section = frappe.db.get_value("Restaurant Section", {"branch": other_branch}, "name")
		table = frappe.db.get_value("Restaurant Table", {"section": section, "is_active": 1}, "name")
		if not table:
			self.skipTest("the other branch has no table")

		frappe.db.set_value("Restaurant Table", table, {"status": "available", "current_order": None})

		with self.assertRaises(frappe.ValidationError):
			self._order(order_type=self.dine_in, table=table, cover_count=2)


class TestSessionOffersEveryHall(OrderTestBase):
	def test_the_payload_lists_the_branch_s_sections(self):
		"""The floor plan needs them all to offer tabs (D-040)."""
		from restaurant_pos.api import session as session_api

		payload = session_api.load_pos_session(self.profile, device_token=test_fixtures.DEVICE_TOKEN)
		names = {row["name"] for row in payload["sections"]}

		self.assertIn(self.section, names, "the terminal's own hall is missing")
		self.assertTrue(
			all(frappe.db.get_value("Restaurant Section", name, "branch") == BRANCH for name in names),
			"a hall from another branch was offered",
		)

	def test_every_order_type_says_who_owes_the_money(self):
		"""D-038 — the screen greys out what it cannot convert to."""
		from restaurant_pos.api import session as session_api

		payload = session_api.load_pos_session(self.profile, device_token=test_fixtures.DEVICE_TOKEN)
		self.assertTrue(payload["order_types"], "no order types in the payload")

		for row in payload["order_types"]:
			self.assertIn(row["counterparty"], ("walk_in", "account"), row["title"])

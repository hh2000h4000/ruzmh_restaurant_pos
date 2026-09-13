# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The "what does this station print" editor.

It writes `POS Printer Routing Rule` rows — the same rows `BR-070` resolves — so
the risk is not what it creates but what it **deletes**. A screen that quietly
removed somebody's carefully scoped rule would be worse than no screen.

Refs: BR-070, D-017, D-095
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant_pos.api import routing as api
from restaurant_pos.tests.test_order import BRANCH

GRILL = "RPOS Test Grill"
FRYER = "RPOS Test Fryer"


def _center(title: str) -> str:
	return frappe.db.get_value("Production Center", {"title": title, "branch": BRANCH}, "name")


class RoutingEditorTestBase(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.grill = _center(GRILL)
		cls.fryer = _center(FRYER)
		cls.group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")

	def setUp(self):
		super().setUp()
		frappe.db.delete("POS Printer Routing Rule", {"branch": BRANCH})


class TestReadingWhatAStationPrints(RoutingEditorTestBase):
	def test_it_lists_every_leaf_group(self):
		"""A parent group would route its children too — not a tick box."""
		state = api.station_groups(self.grill)

		self.assertIn(self.group, state["available"])
		for group in state["available"]:
			self.assertFalse(frappe.db.get_value("Item Group", group, "is_group"))

	def test_it_names_the_station_a_group_is_already_on(self):
		"""Or ticking a box silently takes work off another station."""
		api.set_station_groups(self.fryer, [self.group])

		state = api.station_groups(self.grill)

		self.assertEqual(
			state["elsewhere"].get(self.group),
			frappe.db.get_value("Production Center", self.fryer, "title_ar")
			or frappe.db.get_value("Production Center", self.fryer, "title"),
		)


class TestWritingIt(RoutingEditorTestBase):
	def test_ticking_a_group_creates_a_routing_rule(self):
		api.set_station_groups(self.grill, [self.group])

		self.assertTrue(
			frappe.db.exists(
				"POS Printer Routing Rule",
				{"item_group": self.group, "production_center": self.grill, "is_active": 1},
			)
		)

	def test_unticking_it_deletes_the_rule(self):
		api.set_station_groups(self.grill, [self.group])
		api.set_station_groups(self.grill, [])

		self.assertFalse(
			frappe.db.exists(
				"POS Printer Routing Rule",
				{"item_group": self.group, "production_center": self.grill},
			)
		)

	def test_a_group_belongs_to_one_station(self):
		"""Two stations claiming one group is a coin toss decided by rule age."""
		api.set_station_groups(self.fryer, [self.group])
		api.set_station_groups(self.grill, [self.group])

		owners = frappe.get_all(
			"POS Printer Routing Rule",
			filters={"item_group": self.group, "is_active": 1, "branch": BRANCH},
			pluck="production_center",
		)

		self.assertEqual(owners, [self.grill])

	def test_saving_twice_changes_nothing(self):
		api.set_station_groups(self.grill, [self.group])
		before = frappe.db.count("POS Printer Routing Rule", {"branch": BRANCH})

		api.set_station_groups(self.grill, [self.group])

		self.assertEqual(frappe.db.count("POS Printer Routing Rule", {"branch": BRANCH}), before)


class TestItLeavesTheScopedRulesAlone(RoutingEditorTestBase):
	"""The whole risk of this screen, in three tests."""

	def _scoped(self, **extra) -> str:
		rule = frappe.get_doc(
			{
				"doctype": "POS Printer Routing Rule",
				"branch": BRANCH,
				"item_group": self.group,
				"production_center": self.fryer,
				"priority": 5,
				"is_active": 1,
				**extra,
			}
		)
		rule.insert(ignore_permissions=True)
		return rule.name

	def test_a_rule_scoped_to_an_order_type_survives(self):
		order_type = frappe.db.get_value("Restaurant Order Type", {}, "name")
		scoped = self._scoped(order_type=order_type)

		api.set_station_groups(self.grill, [self.group])

		self.assertTrue(frappe.db.exists("POS Printer Routing Rule", scoped))

	def test_a_rule_for_one_item_survives(self):
		item = frappe.db.get_value("Item", {"is_sales_item": 1}, "name")
		scoped = self._scoped(item=item, item_group=None)

		api.set_station_groups(self.grill, [self.group])

		self.assertTrue(frappe.db.exists("POS Printer Routing Rule", scoped))

	def test_a_scoped_rule_is_not_reported_as_this_station_s(self):
		"""Or unticking a box the screen never set would delete somebody's work."""
		order_type = frappe.db.get_value("Restaurant Order Type", {}, "name")
		self._scoped(order_type=order_type, production_center=self.grill)

		self.assertNotIn(self.group, api.station_groups(self.grill)["assigned"])

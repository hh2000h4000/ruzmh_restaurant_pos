# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Kitchen routing tests — one per level of BR-070, plus tie-breaking.

`06_git_testing_rules.md` requires a test per priority level.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant_pos.utils import routing

BRANCH = "Riyadh"
COMPANY = "Ruzmh Test Co"

GROUP_FOOD = "RPOS Test Food"
GROUP_BURGERS = "RPOS Test Burgers"
ITEM_BURGER = "RPOS-TEST-BURGER"
ITEM_FRIES = "RPOS-TEST-FRIES"


def _group(name: str, parent: str) -> str:
	if not frappe.db.exists("Item Group", name):
		frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": name,
				"parent_item_group": parent,
				"is_group": 0,
			}
		).insert(ignore_permissions=True)
	return name


def _item(code: str, item_group: str) -> str:
	if not frappe.db.exists("Item", code):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_name": code,
				"item_group": item_group,
				"stock_uom": "Nos",
				"is_stock_item": 0,
			}
		).insert(ignore_permissions=True)
	return code


def _center(title: str) -> str:
	existing = frappe.db.get_value("Production Center", {"title": title, "branch": BRANCH}, "name")
	if existing:
		return existing

	return (
		frappe.get_doc(
			{
				"doctype": "Production Center",
				"title": title,
				"title_ar": title,
				"branch": BRANCH,
				"has_kds": 1,
				"kds_display_id": title.lower().replace(" ", "-"),
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


class TestKitchenRouting(FrappeTestCase):
	"""BR-070 — seven levels, highest specificity first."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Branch", BRANCH):
			raise Exception("Test site is missing the Riyadh branch")

		root = frappe.db.get_value("Item Group", {"is_group": 1, "parent_item_group": ""}, "name")
		cls.group_food = _group(GROUP_FOOD, root)
		frappe.db.set_value("Item Group", cls.group_food, "is_group", 1)
		cls.group_burgers = _group(GROUP_BURGERS, cls.group_food)

		cls.item_burger = _item(ITEM_BURGER, cls.group_burgers)
		cls.item_fries = _item(ITEM_FRIES, cls.group_burgers)

		cls.grill = _center("RPOS Test Grill")
		cls.fryer = _center("RPOS Test Fryer")
		cls.bar = _center("RPOS Test Bar")
		cls.cold = _center("RPOS Test Cold")

		cls.order_type = frappe.db.get_value("Restaurant Order Type", {"title": "Dine In"}, "name")
		cls.pos_profile = frappe.db.get_value("POS Profile", {}, "name")
		frappe.db.commit()

	def setUp(self):
		self._clear_rules()
		self._clear_defaults()

	def tearDown(self):
		self._clear_rules()
		self._clear_defaults()

	def _clear_rules(self):
		for name in frappe.get_all("POS Printer Routing Rule", pluck="name"):
			frappe.delete_doc("POS Printer Routing Rule", name, force=True, ignore_permissions=True)

	def _clear_defaults(self):
		for item in (self.item_burger, self.item_fries):
			frappe.db.set_value("Item", item, "default_production_center", None)
		for group in (self.group_food, self.group_burgers):
			frappe.db.set_value("Item Group", group, "default_production_center", None)

	def _rule(self, center, *, order_type=None, pos_profile=None, item=None, item_group=None, priority=10):
		return (
			frappe.get_doc(
				{
					"doctype": "POS Printer Routing Rule",
					"branch": BRANCH,
					"order_type": order_type,
					"pos_profile": pos_profile,
					"item": item,
					"item_group": item_group,
					"production_center": center,
					"priority": priority,
					"is_active": 1,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _resolve(self, item=None):
		return routing.resolve_route(
			item or self.item_burger,
			branch=BRANCH,
			order_type=self.order_type,
			pos_profile=self.pos_profile,
		)

	# ---------------------------------------------------------------- levels

	def test_level_1_order_type_and_item(self):
		self._rule(self.grill, order_type=self.order_type, item=self.item_burger)
		route = self._resolve()
		self.assertEqual(route.level, 1)
		self.assertEqual(route.production_center, self.grill)

	def test_level_2_order_type_and_item_group(self):
		self._rule(self.fryer, order_type=self.order_type, item_group=self.group_burgers)
		route = self._resolve()
		self.assertEqual(route.level, 2)
		self.assertEqual(route.production_center, self.fryer)

	def test_level_3_pos_profile_and_item(self):
		self._rule(self.bar, pos_profile=self.pos_profile, item=self.item_burger)
		route = self._resolve()
		self.assertEqual(route.level, 3)
		self.assertEqual(route.production_center, self.bar)

	def test_level_4_pos_profile_and_item_group(self):
		self._rule(self.cold, pos_profile=self.pos_profile, item_group=self.group_burgers)
		route = self._resolve()
		self.assertEqual(route.level, 4)
		self.assertEqual(route.production_center, self.cold)

	def test_level_5_item_default(self):
		frappe.db.set_value("Item", self.item_burger, "default_production_center", self.grill)
		route = self._resolve()
		self.assertEqual(route.level, 5)
		self.assertEqual(route.production_center, self.grill)

	def test_level_6_item_group_default(self):
		frappe.db.set_value("Item Group", self.group_burgers, "default_production_center", self.fryer)
		route = self._resolve()
		self.assertEqual(route.level, 6)
		self.assertEqual(route.production_center, self.fryer)

	def test_level_7_falls_back_to_the_cashier_printer(self):
		route = self._resolve()
		self.assertEqual(route.level, routing.FALLBACK_LEVEL)
		self.assertIsNone(route.production_center)
		self.assertTrue(route.is_fallback)
		self.assertEqual(
			route.printer,
			frappe.db.get_value("POS Profile", self.pos_profile, "default_printer"),
		)

	# ------------------------------------------------------------- ordering

	def test_all_levels_present_the_most_specific_wins(self):
		"""Every level configured at once — level 1 must win."""
		self._rule(self.grill, order_type=self.order_type, item=self.item_burger)
		self._rule(self.fryer, order_type=self.order_type, item_group=self.group_burgers)
		self._rule(self.bar, pos_profile=self.pos_profile, item=self.item_burger)
		self._rule(self.cold, pos_profile=self.pos_profile, item_group=self.group_burgers)
		frappe.db.set_value("Item", self.item_burger, "default_production_center", self.cold)
		frappe.db.set_value("Item Group", self.group_burgers, "default_production_center", self.cold)

		route = self._resolve()
		self.assertEqual(route.level, 1)
		self.assertEqual(route.production_center, self.grill)

	def test_specificity_beats_priority(self):
		"""D-017: priority breaks ties inside a level, it does not cross levels."""
		self._rule(self.cold, pos_profile=self.pos_profile, item_group=self.group_burgers, priority=1)
		self._rule(self.grill, order_type=self.order_type, item=self.item_burger, priority=99)

		route = self._resolve()
		self.assertEqual(route.level, 1)
		self.assertEqual(route.production_center, self.grill)

	def test_priority_breaks_ties_within_a_level(self):
		self._rule(self.fryer, order_type=self.order_type, item_group=self.group_burgers, priority=20)
		self._rule(self.bar, order_type=self.order_type, item_group=self.group_burgers, priority=5)

		route = self._resolve()
		self.assertEqual(route.level, 2)
		self.assertEqual(route.production_center, self.bar)

	# -------------------------------------------------------------- matching

	def test_a_rule_for_another_order_type_does_not_match(self):
		other = frappe.db.get_value("Restaurant Order Type", {"title": "Takeaway"}, "name")
		self._rule(self.grill, order_type=other, item=self.item_burger)

		self.assertEqual(self._resolve().level, routing.FALLBACK_LEVEL)

	def test_blank_scope_is_a_wildcard(self):
		"""05 §11: a blank order type means every order type."""
		self._rule(self.grill, item=self.item_burger)
		route = self._resolve()
		self.assertEqual(route.production_center, self.grill)

	def test_an_inactive_rule_is_ignored(self):
		name = self._rule(self.grill, order_type=self.order_type, item=self.item_burger)
		frappe.db.set_value("POS Printer Routing Rule", name, "is_active", 0)

		self.assertEqual(self._resolve().level, routing.FALLBACK_LEVEL)

	def test_a_rule_on_a_parent_group_covers_its_children(self):
		"""Item Group is a tree; a rule on the parent must reach the leaf."""
		self._rule(self.grill, order_type=self.order_type, item_group=self.group_food)

		route = self._resolve()
		self.assertEqual(route.level, 2)
		self.assertEqual(route.production_center, self.grill)

	def test_the_nearest_group_default_wins(self):
		frappe.db.set_value("Item Group", self.group_food, "default_production_center", self.bar)
		frappe.db.set_value("Item Group", self.group_burgers, "default_production_center", self.fryer)

		route = self._resolve()
		self.assertEqual(route.production_center, self.fryer)
		self.assertEqual(route.item_group, self.group_burgers)

	# ---------------------------------------------------------------- output

	def test_items_split_across_production_centers(self):
		"""FR-6.3: one order, several centers, one KOT each."""
		self._rule(self.grill, order_type=self.order_type, item=self.item_burger)
		self._rule(self.fryer, order_type=self.order_type, item=self.item_fries)

		routes = routing.resolve_routes(
			[self.item_burger, self.item_fries],
			branch=BRANCH,
			order_type=self.order_type,
			pos_profile=self.pos_profile,
		)
		grouped = routing.group_by_production_center(routes)

		self.assertEqual(set(grouped), {self.grill, self.fryer})
		self.assertEqual(grouped[self.grill], [self.item_burger])
		self.assertEqual(grouped[self.fryer], [self.item_fries])

	def test_resolution_does_not_scale_queries_with_items(self):
		"""04 §Performance: no N+1.

		Resolving twenty lines must cost the same number of reads as resolving
		one. This is the exact pattern the performance rules call out for this
		algorithm, so it is asserted rather than assumed.
		"""
		self._rule(self.grill, order_type=self.order_type, item_group=self.group_burgers)

		def reads_for(items):
			calls = 0
			real_get_all = frappe.get_all

			def counting_get_all(*args, **kwargs):
				nonlocal calls
				calls += 1
				return real_get_all(*args, **kwargs)

			frappe.get_all = counting_get_all
			try:
				routes = routing.resolve_routes(
					items, branch=BRANCH, order_type=self.order_type, pos_profile=self.pos_profile
				)
			finally:
				frappe.get_all = real_get_all

			return calls, routes

		one_call_count, one = reads_for([self.item_burger])
		many_items = [self.item_burger, self.item_fries] * 10
		many_call_count, many = reads_for(many_items)

		self.assertEqual(len(one), 1)
		self.assertEqual(len(many), 2)  # deduplicated
		self.assertEqual(
			many_call_count,
			one_call_count,
			"routing issued more reads for more items — N+1 has crept in",
		)

	def test_printer_lookup_reports_primary_and_fallback(self):
		"""BR-071/BR-072 — the caller needs both to implement failover."""
		center = routing.printer_for(self.grill)
		self.assertIn("printer", center)
		self.assertIn("fallback_printer", center)


OTHER_BRANCH = "RPOS Test Other Branch"


def _other_grill() -> str:
	"""A station of a second branch, which the order's branch must not print at."""
	if not frappe.db.exists("Branch", OTHER_BRANCH):
		other = frappe.copy_doc(frappe.get_doc("Branch", BRANCH))
		other.branch = OTHER_BRANCH
		# Its own invoice number; a copy would claim the first branch's (`D-309`).
		other.rpos_branch_number = None
		other.insert(ignore_permissions=True)
	existing = frappe.db.get_value(
		"Production Center", {"title": "RPOS Other Grill", "branch": OTHER_BRANCH}, "name"
	)
	return existing or (
		frappe.get_doc(
			{
				"doctype": "Production Center",
				"title": "RPOS Other Grill",
				"title_ar": "RPOS Other Grill",
				"branch": OTHER_BRANCH,
				"has_kds": 1,
				"kds_display_id": "rpos-other-grill",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


class AnotherBranchsStationIsNotThisBranchs(TestKitchenRouting):
	"""`D-361` — an item's default station belongs to one branch; another branch selling it does not print there."""

	def test_an_item_default_in_another_branch_falls_through_to_the_cashier(self):
		frappe.db.set_value("Item", self.item_burger, "default_production_center", _other_grill())

		route = self._resolve()

		self.assertIsNone(route.production_center)
		self.assertTrue(route.is_fallback)

	def test_it_falls_through_to_this_branchs_group_default(self):
		frappe.db.set_value("Item", self.item_burger, "default_production_center", _other_grill())
		frappe.db.set_value("Item Group", self.group_burgers, "default_production_center", self.grill)

		route = self._resolve()

		self.assertEqual((route.production_center, route.level), (self.grill, 6))

	def test_a_station_of_this_branch_is_still_the_items_default(self):
		frappe.db.set_value("Item", self.item_burger, "default_production_center", self.grill)

		self.assertEqual(self._resolve().production_center, self.grill)

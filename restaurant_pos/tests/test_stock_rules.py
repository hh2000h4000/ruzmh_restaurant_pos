# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The stock settings do not contradict each other (`D-337`).

The site's "Allow Negative Stock" is the ceiling: where it is off, every branch
refuses a sale when stock is short — a branch that refused nothing would sell
all day and be unable to post its stock at night. And a branch has one
warehouse, which its terminals take.
"""

import frappe

from restaurant_pos.tests.test_order import BRANCH, OrderTestBase
from restaurant_pos.utils import stock_rules


class StockRulesTestBase(OrderTestBase):
	def _negative(self, allowed: int) -> None:
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock", allowed)
		frappe.db.value_cache = {}

	def _branch(self, enforce: int):
		frappe.db.set_value("Branch", BRANCH, stock_rules.ENFORCE, enforce)
		frappe.clear_document_cache("Branch", BRANCH)
		return frappe.get_doc("Branch", BRANCH)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()


class TheSiteSettingIsTheCeiling(StockRulesTestBase):
	def test_a_branch_cannot_stop_refusing_where_negative_stock_is_not_allowed(self):
		self._negative(0)
		branch = self._branch(1)
		branch.set(stock_rules.ENFORCE, 0)

		self.assertRaises(frappe.ValidationError, branch.save, ignore_permissions=True)

	def test_it_may_where_negative_stock_is_allowed(self):
		self._negative(1)
		branch = self._branch(1)
		branch.set(stock_rules.ENFORCE, 0)

		branch.save(ignore_permissions=True)

		self.assertEqual(frappe.db.get_value("Branch", BRANCH, stock_rules.ENFORCE), 0)

	def test_a_branch_already_set_that_way_can_still_be_saved(self):
		"""Other fields must stay editable on a site that was contradictory before the rule."""
		self._negative(0)
		branch = self._branch(0)
		branch.phone = "0500000000"

		branch.save(ignore_permissions=True)

	def test_a_new_branch_starts_the_only_way_the_site_lets_it(self):
		self._negative(0)
		source = frappe.get_doc("Branch", BRANCH)
		fresh = frappe.copy_doc(source)
		fresh.branch = "RPOS Ceiling Test Branch"
		fresh.set(stock_rules.ENFORCE, 0)
		fresh.rpos_branch_number = None

		fresh.insert(ignore_permissions=True)

		self.assertEqual(fresh.get(stock_rules.ENFORCE), 1)

	def test_turning_negative_stock_off_names_the_branches_that_no_longer_fit(self):
		self._negative(1)
		self._branch(0)
		settings = frappe.get_doc("Stock Settings")
		settings.allow_negative_stock = 0
		frappe.clear_messages()

		stock_rules.warn_when_the_ceiling_drops(settings)

		said = " ".join(str(message) for message in frappe.get_message_log())
		self.assertIn(BRANCH, said)
		frappe.clear_messages()

	def test_and_says_nothing_when_every_branch_already_refuses(self):
		self._negative(1)
		frappe.db.set_value("Branch", {"name": ("is", "set")}, stock_rules.ENFORCE, 1)
		settings = frappe.get_doc("Stock Settings")
		settings.allow_negative_stock = 0
		frappe.clear_messages()

		stock_rules.warn_when_the_ceiling_drops(settings)

		self.assertEqual(frappe.get_message_log(), [])


class OneWarehouse(StockRulesTestBase):
	def test_a_terminal_with_none_of_its_own_takes_its_branch_s(self):
		profile = frappe.get_doc("POS Profile", self.profile)
		expected = frappe.db.get_value("Branch", BRANCH, "default_warehouse")
		profile.warehouse = None

		stock_rules.take_the_branch_warehouse(profile)

		self.assertEqual(profile.warehouse, expected)

	def test_a_terminal_given_its_own_keeps_it(self):
		profile = frappe.get_doc("POS Profile", self.profile)
		own = profile.warehouse

		stock_rules.take_the_branch_warehouse(profile)

		self.assertEqual(profile.warehouse, own)

	def test_terminals_on_the_branch_s_warehouse_follow_it_when_it_changes(self):
		was = frappe.db.get_value("Branch", BRANCH, "default_warehouse")
		frappe.db.set_value("POS Profile", self.profile, "warehouse", was)
		other = frappe.db.get_value(
			"Warehouse",
			{"is_group": 0, "name": ("!=", was), "company": frappe.db.get_value("Branch", BRANCH, "company")},
		)
		branch = frappe.get_doc("Branch", BRANCH)
		branch.default_warehouse = other

		branch.save(ignore_permissions=True)

		self.assertEqual(frappe.db.get_value("POS Profile", self.profile, "warehouse"), other)

	def test_a_terminal_put_elsewhere_on_purpose_stays_there(self):
		was = frappe.db.get_value("Branch", BRANCH, "default_warehouse")
		company = frappe.db.get_value("Branch", BRANCH, "company")
		others = frappe.get_all(
			"Warehouse",
			filters={"is_group": 0, "name": ("!=", was), "company": company},
			pluck="name",
			limit=2,
		)
		if len(others) < 2:
			self.skipTest("the test company has fewer than three warehouses")
		frappe.db.set_value("POS Profile", self.profile, "warehouse", others[0])
		branch = frappe.get_doc("Branch", BRANCH)
		branch.default_warehouse = others[1]

		branch.save(ignore_permissions=True)

		self.assertEqual(frappe.db.get_value("POS Profile", self.profile, "warehouse"), others[0])


class TheFormsSayTheSiteSetting(StockRulesTestBase):
	def test_the_branch_and_the_settings_are_handed_the_same_sentence(self):
		self._negative(1)
		branch = frappe.get_doc("Branch", BRANCH)
		settings = frappe.get_doc("Restaurant POS Settings")

		stock_rules.say_the_site_setting(branch)
		settings.onload()

		self.assertEqual(branch.get_onload("rpos_stock_note"), settings.get_onload("rpos_stock_note"))
		self.assertIn("allowed", branch.get_onload("rpos_stock_note"))

	def test_it_says_which_way_the_site_is_set(self):
		self._negative(0)
		branch = frappe.get_doc("Branch", BRANCH)

		stock_rules.say_the_site_setting(branch)

		self.assertIn("not allowed", branch.get_onload("rpos_stock_note"))

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Quick setup (`D-307`): from an installed app to a till that can sell, in one form."""

import uuid

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant_pos.api import quick_setup as api
from restaurant_pos.utils import quick_setup as service


def _answers(**over) -> dict:
	tag = uuid.uuid4().hex[:6]
	return {
		"company": frappe.db.get_value("Company", {}, "name"),
		"branch": f"RPOS Quick {tag}",
		"dine_in": 1,
		"tables": 3,
		"terminal": f"RPOS Quick Till {tag}",
		**over,
	}


class QuickSetupMakesATillThatCanSell(FrappeTestCase):
	def test_the_branch_its_hall_tables_and_terminal_are_made(self):
		answers = _answers()

		made = service.run(answers)

		self.assertEqual(made["branch"], answers["branch"])
		branch = frappe.get_doc("Branch", made["branch"])
		self.assertTrue(branch.default_warehouse)
		self.assertTrue(branch.default_cost_center)

		# `D-395` — one hall, for the tables. Takeaway and delivery are order
		# types; no hall is made for them.
		self.assertEqual(len(made["sections"]), 1)
		hall = made["sections"][0]
		self.assertEqual(frappe.db.count("Restaurant Table", {"section": hall}), 3)

		profile = frappe.get_doc("POS Profile", made["pos_profile"])
		self.assertEqual(profile.rpos_branch, made["branch"], "the terminal belongs to the branch")
		self.assertEqual(profile.restaurant_section, hall, "and opens on the hall")
		self.assertEqual([row.mode_of_payment for row in profile.payments], ["Cash"])
		self.assertTrue(profile.selling_price_list)

	def test_the_branch_does_not_sell_out_of_the_transit_warehouse(self):
		"""`D-345` — the company's first warehouse by name is «Goods In Transit»."""
		values = _answers()
		transit = frappe.db.get_value("Company", values["company"], "default_in_transit_warehouse")

		service.run(values)

		chosen = frappe.db.get_value("Branch", values["branch"], "default_warehouse")
		self.assertNotEqual(chosen, transit)
		self.assertNotEqual(frappe.db.get_value("Warehouse", chosen, "warehouse_type"), "Transit")
		self.assertEqual(frappe.db.get_value("POS Profile", values["terminal"], "warehouse"), chosen)

	def test_the_till_opens_at_the_shops_own_prices(self):
		"""`D-345` — the first selling list was a delivery app's."""
		usual = frappe.db.get_single_value("Selling Settings", "selling_price_list")
		if not usual:
			self.skipTest("the site names no default selling price list")
		values = _answers()

		service.run(values)

		self.assertEqual(frappe.db.get_value("POS Profile", values["terminal"], "selling_price_list"), usual)

	def test_it_lets_stock_go_below_zero_and_says_so_once(self):
		"""`D-326` — a kitchen that enters its deliveries late must still have its day posted."""
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 0)

		self.assertTrue(service._let_stock_go_below_zero())
		self.assertEqual(frappe.db.get_single_value("Stock Settings", "allow_negative_stock"), 1)
		self.assertFalse(service._let_stock_go_below_zero(), "already on: nothing to say")

	def test_it_hands_back_a_pairing_code_for_the_till(self):
		made = service.run(_answers())

		self.assertTrue(made["pairing_code"])
		self.assertTrue(frappe.db.get_value("POS Profile", made["pos_profile"], "rpos_pairing_code_hash"))

	def test_a_counter_branch_has_no_hall_and_its_terminal_belongs_to_the_branch(self):
		"""`D-395` — a counter or a supermarket: no hall, no tables, a till all the same."""
		made = service.run(_answers(dine_in=0))

		self.assertEqual(made["tables"], 0)
		self.assertEqual(made["sections"], [])
		profile = frappe.get_doc("POS Profile", made["pos_profile"])
		self.assertEqual(profile.rpos_branch, made["branch"])
		self.assertFalse(profile.restaurant_section)

	def test_a_name_already_taken_is_refused_before_anything_is_made(self):
		first = service.run(_answers())
		again = _answers(branch=first["branch"])

		with self.assertRaises(frappe.ValidationError):
			service.run(again)
		self.assertFalse(frappe.db.exists("POS Profile", again["terminal"]))

	def test_a_hall_needs_at_least_one_table(self):
		with self.assertRaises(frappe.ValidationError):
			service.run(_answers(dine_in=1, tables=0))

	def test_somebody_who_may_not_create_a_branch_is_told_so(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				api.run(_answers())
		finally:
			frappe.set_user("Administrator")

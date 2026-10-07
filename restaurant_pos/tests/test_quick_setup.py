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
		"takeaway": 1,
		"delivery": 0,
		"terminal": f"RPOS Quick Till {tag}",
		**over,
	}


class QuickSetupMakesATillThatCanSell(FrappeTestCase):
	def test_the_branch_its_sections_tables_and_terminal_are_made(self):
		answers = _answers()

		made = service.run(answers)

		self.assertEqual(made["branch"], answers["branch"])
		branch = frappe.get_doc("Branch", made["branch"])
		self.assertTrue(branch.default_warehouse)
		self.assertTrue(branch.default_cost_center)

		kinds = sorted(
			frappe.db.get_value("Restaurant Section", name, "section_type") for name in made["sections"]
		)
		self.assertEqual(kinds, ["dine_in", "takeaway"])

		hall = next(
			name
			for name in made["sections"]
			if frappe.db.get_value("Restaurant Section", name, "section_type") == "dine_in"
		)
		self.assertEqual(frappe.db.count("Restaurant Table", {"section": hall}), 3)

		profile = frappe.get_doc("POS Profile", made["pos_profile"])
		self.assertEqual(profile.restaurant_section, hall, "the hall is the terminal's home")
		self.assertEqual([row.mode_of_payment for row in profile.payments], ["Cash"])
		self.assertTrue(profile.selling_price_list)

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

	def test_a_takeaway_only_branch_has_no_tables(self):
		made = service.run(_answers(dine_in=0, delivery=1))

		self.assertEqual(made["tables"], 0)
		for name in made["sections"]:
			self.assertEqual(frappe.db.count("Restaurant Table", {"section": name}), 0)

	def test_a_name_already_taken_is_refused_before_anything_is_made(self):
		first = service.run(_answers())
		again = _answers(branch=first["branch"])

		with self.assertRaises(frappe.ValidationError):
			service.run(again)
		self.assertFalse(frappe.db.exists("POS Profile", again["terminal"]))

	def test_a_branch_with_nothing_in_it_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			service.run(_answers(dine_in=0, takeaway=0, delivery=0))

	def test_somebody_who_may_not_create_a_branch_is_told_so(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				api.run(_answers())
		finally:
			frappe.set_user("Administrator")

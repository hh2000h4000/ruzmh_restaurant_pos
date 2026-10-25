# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""A device is its branch: the rest of ERPNext's form is filled from it (`D-400`).

Refs: D-337, D-392, D-400
"""

import uuid

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant_pos.setup.install import TERMINAL_FORM_ORDER
from restaurant_pos.setup.test_fixtures import BRANCH, PROFILE
from restaurant_pos.utils import terminal_defaults


def _new(**fields):
	return frappe.get_doc(
		{"doctype": "POS Profile", "name": f"RPOS Defaults Till {uuid.uuid4().hex[:6]}", **fields}
	)


class ADeviceIsItsBranch(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.company = frappe.db.get_value("Branch", BRANCH, "company")
		self.vat = frappe.db.get_value("POS Profile", PROFILE, "taxes_and_charges")

	def test_a_branch_and_nothing_else_makes_a_device_that_saves(self):
		"""Everything ERPNext requires is answered by the branch."""
		doc = _new(rpos_branch=BRANCH, taxes_and_charges=self.vat).insert(ignore_permissions=True)

		self.assertEqual(doc.company, self.company)
		self.assertEqual(doc.warehouse, frappe.db.get_value("Branch", BRANCH, "default_warehouse"))
		self.assertEqual(doc.currency, frappe.db.get_value("Company", self.company, "default_currency"))
		self.assertTrue(doc.write_off_account)
		self.assertTrue(doc.write_off_cost_center)
		self.assertTrue(doc.customer)
		self.assertTrue(doc.selling_price_list)
		self.assertEqual(len(doc.payments), 1)

	def test_what_was_chosen_is_kept(self):
		"""A device set apart from its branch on purpose stays apart."""
		chosen = frappe.db.get_value(
			"Price List", {"selling": 1, "enabled": 1}, "name", order_by="creation desc"
		)
		doc = _new(rpos_branch=BRANCH, taxes_and_charges=self.vat, selling_price_list=chosen)

		terminal_defaults.fill_from_branch(doc)

		self.assertEqual(doc.selling_price_list, chosen)
		self.assertEqual(doc.taxes_and_charges, self.vat)

	def test_the_tax_comes_from_the_company_default(self):
		doc = _new(rpos_branch=BRANCH)
		default = terminal_defaults.default_tax_template(self.company)

		terminal_defaults.fill_from_branch(doc)

		self.assertEqual(doc.taxes_and_charges, default)

	def test_with_no_default_tax_the_device_is_refused_not_saved_without_vat(self):
		if terminal_defaults.default_tax_template(self.company):
			self.skipTest("this company marks a default tax template")
		with self.assertRaises(frappe.MandatoryError):
			_new(rpos_branch=BRANCH).insert(ignore_permissions=True)

	def test_a_device_with_no_branch_is_refused(self):
		with self.assertRaises(frappe.MandatoryError):
			_new(company=self.company, taxes_and_charges=self.vat).insert(ignore_permissions=True)


class TheFormFillsWhenTheBranchIsPicked(FrappeTestCase):
	"""The browser checks required fields before a save reaches the server, so the
	form asks for the answers as soon as the branch is chosen (`D-400`)."""

	def test_the_form_is_given_what_the_save_would_fill(self):
		from restaurant_pos.api import desk

		frappe.set_user("Administrator")
		answers = desk.terminal_defaults(BRANCH)

		saved = _new(rpos_branch=BRANCH)
		terminal_defaults.fill_from_branch(saved)
		for field in terminal_defaults.FILLED:
			self.assertEqual(answers[field], saved.get(field), field)
		self.assertEqual([row["mode_of_payment"] for row in answers["payments"]], ["Cash"])

	def test_a_cashier_cannot_ask_for_them(self):
		from restaurant_pos.api import desk
		from restaurant_pos.tests.test_permissions import CASHIER, _make_user

		frappe.set_user(_make_user(CASHIER, "POS Cashier"))
		try:
			with self.assertRaises(frappe.PermissionError):
				desk.terminal_defaults(BRANCH)
		finally:
			frappe.set_user("Administrator")


class TheFormAsksTheEssentialsFirst(FrappeTestCase):
	def test_the_required_fields_lead_the_form(self):
		meta = frappe.get_meta("POS Profile", cached=False)
		names = [df.fieldname for df in meta.fields]
		essentials = names[: names.index("rpos_accounting_section")]

		for field in (
			"rpos_branch",
			"company",
			"customer",
			"taxes_and_charges",
			"selling_price_list",
			"payments",
		):
			self.assertIn(field, essentials)
			self.assertTrue(meta.get_field(field).reqd, field)

	def test_every_named_field_exists(self):
		"""A field ERPNext renames would silently drop out of the order."""
		meta = frappe.get_meta("POS Profile", cached=False)
		missing = [name for name in TERMINAL_FORM_ORDER if not meta.has_field(name)]
		self.assertEqual(missing, [])

	def test_the_device_list_shows_and_filters_by_branch(self):
		"""`D-401` — the column that tells tills apart."""
		branch = frappe.get_meta("POS Profile", cached=False).get_field("rpos_branch")
		self.assertTrue(branch.in_list_view)
		self.assertTrue(branch.in_standard_filter)

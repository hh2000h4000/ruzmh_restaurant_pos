# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""ERPNext fields a till cannot work without (`D-231`).

**Written because a terminal saved happily without one and then refused every
sale.** A `POS Profile` with no default customer looks complete: nothing on the
form marks it, and the refusal arrives at the payment screen, in red, with a
queue waiting. The user met it on their own till.

So the asking moves to the form, where the manager is already standing.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant_pos.setup.install import REQUIRED_ERPNEXT_FIELDS, require_erpnext_fields
from restaurant_pos.setup.test_fixtures import PROFILE
from restaurant_pos.utils import quick_setup


class TestRequiredErpnextFields(FrappeTestCase):
	def test_the_form_asks_for_them(self):
		require_erpnext_fields()

		for doctype, fieldname in REQUIRED_ERPNEXT_FIELDS:
			with self.subTest(field=f"{doctype}.{fieldname}"):
				self.assertEqual(
					frappe.get_meta(doctype).get_field(fieldname).reqd,
					1,
					f"{doctype}.{fieldname} must be required on the form",
				)

	def test_each_one_says_why_on_the_field(self):
		"""A required field with no reason is a wall; the manager needs the sentence."""
		require_erpnext_fields()

		for (doctype, fieldname), description in REQUIRED_ERPNEXT_FIELDS.items():
			with self.subTest(field=f"{doctype}.{fieldname}"):
				self.assertEqual(frappe.get_meta(doctype).get_field(fieldname).description, description)

	def test_a_terminal_is_never_saved_with_no_customer(self):
		"""Required on the form — and an emptied one is filled from the branch's defaults (`D-400`)."""
		require_erpnext_fields()
		frappe.clear_cache(doctype="POS Profile")
		self.assertTrue(frappe.get_meta("POS Profile").get_field("customer").reqd)

		profile = frappe.get_doc("POS Profile", PROFILE)
		profile.customer = None
		profile.save(ignore_permissions=True)

		self.assertEqual(profile.customer, quick_setup.walk_in_customer())

	def test_applying_it_twice_changes_nothing(self):
		"""`after_migrate` runs it on every migrate."""
		require_erpnext_fields()
		require_erpnext_fields()

		for doctype, fieldname in REQUIRED_ERPNEXT_FIELDS:
			self.assertEqual(
				frappe.db.count("Property Setter", {"doc_type": doctype, "field_name": fieldname}),
				2,
				"one setter for `reqd`, one for `description`, however often it runs",
			)

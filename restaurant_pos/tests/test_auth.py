# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""PIN sign-in and attendance.

The PIN is now an identity, not only an approval, and that changes what a
collision costs: two people sharing one would have the second signing in **as**
the first, with every order recorded against somebody who was not there.

Refs: FR-8.4, FR-12.2, D-057, D-094
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant_pos.utils import attendance
from restaurant_pos.utils import manager_pin as pins

STAFF = "rpos_pin_staff@example.com"
OTHER = "rpos_pin_other@example.com"


def _user(email: str) -> str:
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"roles": [{"role": "POS Cashier"}],
			}
		).insert(ignore_permissions=True)
	return email


class TestFindingSomebodyByPin(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_user(STAFF)
		_user(OTHER)
		frappe.db.commit()

	def setUp(self):
		super().setUp()
		pins.set_pin(STAFF, "51234")

	def test_the_right_pin_finds_the_right_person(self):
		self.assertEqual(pins.find_user_by_pin("51234"), STAFF)

	def test_a_wrong_pin_finds_nobody(self):
		self.assertIsNone(pins.find_user_by_pin("99999"))

	def test_setting_a_pin_writes_the_lookup_index(self):
		"""Without it the sign-in falls back to hashing every member of staff."""
		self.assertEqual(
			frappe.db.get_value("User", STAFF, pins.LOOKUP_FIELD),
			pins.lookup_of("51234"),
		)

	def test_the_index_is_a_digest_and_not_the_pin(self):
		stored = frappe.db.get_value("User", STAFF, pins.LOOKUP_FIELD)

		self.assertNotIn("51234", stored)
		self.assertEqual(len(stored), 64)

	def test_a_pin_set_before_the_index_existed_still_works(self):
		"""The hash is one way, so an upgrade could not backfill the digest.

		Rather than deleting every PIN and asking a restaurant to reissue them,
		the first sign-in with an old one falls back to the scan and writes the
		digest on its way through (`D-094`).
		"""
		frappe.db.set_value("User", STAFF, pins.LOOKUP_FIELD, None, update_modified=False)

		self.assertEqual(pins.find_user_by_pin("51234"), STAFF)
		self.assertEqual(
			frappe.db.get_value("User", STAFF, pins.LOOKUP_FIELD),
			pins.lookup_of("51234"),
			"the fallback must index it, or every sign-in pays the old cost",
		)

	def test_clearing_a_pin_clears_the_index(self):
		"""A digest left behind finds a user whose PIN no longer verifies."""
		pins.clear_pin(STAFF)

		self.assertIsNone(frappe.db.get_value("User", STAFF, pins.LOOKUP_FIELD))
		self.assertIsNone(pins.find_user_by_pin("51234"))


class TestTwoPeopleCannotShareAPin(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_user(STAFF)
		_user(OTHER)
		frappe.db.commit()

	def test_a_taken_pin_is_refused(self):
		pins.set_pin(STAFF, "51234")

		with self.assertRaises(frappe.ValidationError):
			pins.set_pin(OTHER, "51234")

	def test_a_legacy_pin_still_counts_as_taken(self):
		"""Checking only the index would hand out a colliding PIN."""
		pins.set_pin(STAFF, "51234")
		frappe.db.set_value("User", STAFF, pins.LOOKUP_FIELD, None, update_modified=False)

		with self.assertRaises(frappe.ValidationError):
			pins.set_pin(OTHER, "51234")

	def test_a_person_may_keep_their_own_pin(self):
		pins.set_pin(STAFF, "51234")
		pins.set_pin(STAFF, "51234")


class TestClockingInAndOut(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_user(STAFF)
		frappe.db.commit()

	def test_somebody_with_no_employee_record_is_not_clocked_in(self):
		"""Signing in still works; only the attendance buttons go away."""
		state = attendance.state(STAFF)

		self.assertIsNone(state["employee"])
		self.assertFalse(state["clocked_in"])

	def test_clocking_in_without_an_employee_record_says_so(self):
		with self.assertRaises(frappe.ValidationError):
			attendance.punch(STAFF, log_type=attendance.IN)

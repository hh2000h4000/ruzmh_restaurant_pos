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


class TestAHandoverDoesNotInheritPermissions(FrappeTestCase):
	"""Why the till reloads its session when somebody signs in (`D-096`).

	The terminal payload carries `permissions`, and permissions belong to the
	person rather than to the machine. The screen caches that payload for the
	menu and the branch, which do not change at a handover — but the permissions
	do, and a cashier taking over would otherwise be looking at the last one's
	buttons.
	"""

	def test_the_terminal_payload_is_scoped_to_whoever_asks(self):
		from restaurant_pos.utils.permissions import get_pos_permission_set

		manager = _user("rpos_pin_manager@example.com")
		doc = frappe.get_doc("User", manager)
		if "POS Manager" not in [row.role for row in doc.roles]:
			doc.append("roles", {"role": "POS Manager"})
			doc.save(ignore_permissions=True)

		cashier_rights = get_pos_permission_set(STAFF)
		manager_rights = get_pos_permission_set(manager)

		self.assertNotEqual(
			cashier_rights.get("roles"),
			manager_rights.get("roles"),
			"if two roles carried the same rights this test proves nothing",
		)
		self.assertNotEqual(
			cashier_rights.get("can_void_order"),
			manager_rights.get("can_void_order"),
		)


class TestWhyAPinWasRefused(FrappeTestCase):
	"""The cashier gets one sentence; the audit log gets the reason (`D-099`).

	A PIN refused because the account has no POS role reads, at the pad,
	exactly like a mistyped one — deliberately, so an attacker cannot tell
	which guesses were close. Without the reason recorded somewhere, the person
	who set the account up has nothing to go on. It cost an afternoon on the
	demo: a PIN was set, a role was not, and the pad said only "not recognised".
	"""

	def test_a_pin_with_no_pos_role_is_refused_and_the_reason_recorded(self):
		from restaurant_pos.api import auth

		user = _user("rpos_pin_noroles@example.com")
		doc = frappe.get_doc("User", user)
		doc.set("roles", [])
		doc.save(ignore_permissions=True)
		pins.set_pin(user, "58888")

		self.assertFalse(auth._may_use_the_till(user))

	def test_somebody_with_a_role_may_use_the_till(self):
		from restaurant_pos.api import auth

		self.assertTrue(auth._may_use_the_till(_user(STAFF)))


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


class TestAPunchThatActuallyLands(FrappeTestCase):
	"""The half of `FR-8.4` nothing covered, and what that cost.

	Every test above this one runs with **no** `Employee` behind the login, so
	the service returned early and the punch itself was never executed. It hid a
	fault the size of the feature: `Employee Checkin` ships in **hrms**, which
	was installed on no site, and the first member of staff to press حضور would
	have met an internal error (`D-135`). `frappe.db.get_value` on an absent
	table answers `None` rather than raising, so nothing anywhere said so.

	These tests need a real employee, so they skip where there is none to build
	one from — but on a site with hrms they exercise the write.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_user(STAFF)
		frappe.db.commit()

	def setUp(self):
		super().setUp()
		if not frappe.db.exists("DocType", "Employee Checkin"):
			self.skipTest("hrms is not installed on this site")

		self.employee = _employee_for(STAFF)
		if not self.employee:
			self.skipTest("this site cannot create an Employee (no company or holiday list)")

		frappe.db.delete("Employee Checkin", {"employee": self.employee})

	def test_a_punch_lands_and_the_state_says_so(self):
		state = attendance.punch(STAFF, log_type=attendance.IN)

		self.assertTrue(state["clocked_in"])
		self.assertIsNotNone(state["since"])
		self.assertEqual(state["employee"], self.employee)

	def test_the_punch_records_which_terminal_it_happened_at(self):
		"""So a manager reading it back knows where somebody started."""
		attendance.punch(STAFF, log_type=attendance.IN, pos_profile="T1")

		self.assertEqual(
			frappe.db.get_value(
				"Employee Checkin", {"employee": self.employee}, "device_id", order_by="creation desc"
			),
			"T1",
		)

	def test_clocking_in_twice_is_refused(self):
		"""Not a harmless duplicate: it is a shift whose length cannot be
		computed, and it is what a doubled tap produces."""
		attendance.punch(STAFF, log_type=attendance.IN)

		with self.assertRaises(frappe.ValidationError):
			attendance.punch(STAFF, log_type=attendance.IN)

	def test_clocking_out_when_never_in_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			attendance.punch(STAFF, log_type=attendance.OUT)

	def test_in_then_out_closes_the_day(self):
		attendance.punch(STAFF, log_type=attendance.IN)
		state = attendance.punch(STAFF, log_type=attendance.OUT)

		self.assertFalse(state["clocked_in"])
		self.assertIsNone(state["since"])


def _employee_for(user: str) -> str | None:
	"""An Active employee tied to this login, made once and reused.

	`Employee` is mandatory-heavy — a company, a date of joining, a gender, a
	date of birth — so this builds the smallest record ERPNext will accept and
	gives up rather than failing the suite on a site set up differently.
	"""
	existing = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
	if existing:
		return existing

	company = frappe.db.get_value("Company", {}, "name")
	if not company:
		return None

	try:
		return (
			frappe.get_doc(
				{
					"doctype": "Employee",
					"first_name": "RPOS Attendance",
					"user_id": user,
					"company": company,
					"gender": frappe.db.get_value("Gender", {}, "name") or "Other",
					"date_of_birth": "1990-01-01",
					"date_of_joining": "2020-01-01",
					"status": "Active",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
	except Exception:
		return None

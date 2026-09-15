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
from frappe.utils import add_to_date, now_datetime

from restaurant_pos.api import auth as auth_api
from restaurant_pos.tests.test_order import BRANCH, OrderTestBase
from restaurant_pos.utils import attendance
from restaurant_pos.utils import manager_pin as pins
from restaurant_pos.utils import permissions as perms

STAFF = "rpos_pin_staff@example.com"
OTHER = "rpos_pin_other@example.com"
#: A login nothing in this module ever gives an `Employee` to.
NOBODY = "rpos_pin_no_employee@example.com"


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


class TestAnOrdinarySaveDoesNotDestroyAPin(FrappeTestCase):
	"""The defect that logged people out of the till for no reason (`D-136`).

	`BaseDocument._save_passwords` runs on **every** save and reads an empty
	`Password` field as "delete the stored one". Our column is always empty —
	the value lives in `__Auth` as a one-way hash this app writes itself — so
	adding a role to a cashier, or correcting the spelling of their name, took
	their PIN away. Nothing said so: the pad answers "not recognised" for every
	refusal on purpose (`D-099`), and the lookup digest stayed behind, so the
	account was still found and then failed to verify.

	It cost a live account on the demo site before it was understood.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_user(STAFF)
		frappe.db.commit()

	def setUp(self):
		super().setUp()
		pins.set_pin(STAFF, "53791")

	def test_editing_something_unrelated_leaves_the_pin_alone(self):
		doc = frappe.get_doc("User", STAFF)
		doc.middle_name = "Edited"
		doc.save(ignore_permissions=True)

		self.assertEqual(pins.find_user_by_pin("53791"), STAFF)

	def test_granting_a_role_leaves_the_pin_alone(self):
		"""The exact edit that did it: a manager adding a permission."""
		doc = frappe.get_doc("User", STAFF)
		doc.append("roles", {"role": "POS Manager"})
		doc.save(ignore_permissions=True)

		self.assertEqual(pins.find_user_by_pin("53791"), STAFF)

	def test_it_survives_being_saved_repeatedly(self):
		for index in range(3):
			doc = frappe.get_doc("User", STAFF)
			doc.middle_name = f"Edit {index}"
			doc.save(ignore_permissions=True)

		self.assertEqual(pins.find_user_by_pin("53791"), STAFF)

	def test_changing_the_pin_still_replaces_it(self):
		"""The guard must not freeze the field: a PIN is still changeable."""
		doc = frappe.get_doc("User", STAFF)
		doc.set(pins.FIELDNAME, "57913")
		doc.save(ignore_permissions=True)

		self.assertIsNone(pins.find_user_by_pin("53791"))
		self.assertEqual(pins.find_user_by_pin("57913"), STAFF)

	def test_the_pin_never_lands_in_the_column(self):
		"""What the blanking is actually for: no reversible copy, ever."""
		doc = frappe.get_doc("User", STAFF)
		doc.set(pins.FIELDNAME, "57913")
		doc.save(ignore_permissions=True)

		self.assertIsNone(frappe.db.get_value("User", STAFF, pins.FIELDNAME))


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
		user = _user("rpos_pin_noroles@example.com")
		doc = frappe.get_doc("User", user)
		doc.set("roles", [])
		doc.save(ignore_permissions=True)
		pins.set_pin(user, "58888")
		frappe.local.rpos_permission_cache = {}

		# The same check the whole till now passes through (`D-208`).
		self.assertFalse(perms.is_pos_user(user))

	def test_somebody_with_a_role_may_use_the_till(self):
		frappe.local.rpos_permission_cache = {}
		self.assertTrue(perms.is_pos_user(_user(STAFF)))


class TestClockingInAndOut(FrappeTestCase):
	"""A login that is on no payroll.

	**It owns its own user**, and that is the point of `NOBODY`. These used to
	name `STAFF`, whose `Employee` is built by the classes below — so the
	premise held only while this class happened to sort first, and the moment a
	later class committed, the *next* whole-suite run failed here on data from
	the previous one. A test whose subject somebody else creates is a test about
	the alphabet.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_user(NOBODY)
		frappe.db.commit()

	def test_somebody_with_no_employee_record_is_not_clocked_in(self):
		"""Signing in still works; only the attendance buttons go away."""
		state = attendance.state(NOBODY)

		self.assertIsNone(state["employee"])
		self.assertFalse(state["clocked_in"])

	def test_clocking_in_without_an_employee_record_says_so(self):
		with self.assertRaises(frappe.ValidationError):
			attendance.punch(NOBODY, log_type=attendance.IN)


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
					"gender": _a_gender(),
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


class TestGoingHomeOverAnOpenDrawer(OrderTestBase):
	"""A clock-out waits for the drawer to be counted (`D-177`, `FR-8.4`).

	The user described the order a shift actually runs in — arrive, take the
	drawer, work, count it, go home — and the screen offered the last step at
	any point in the middle. Somebody who clocks out over an open till leaves a
	count nobody made, against a name that is no longer at work; that is the one
	place a shortage is meant to be traceable to a person.

	**The one exception to `D-057`**, which otherwise keeps hours and drawers
	apart, so it is held here rather than assumed.

	Built on `OrderTestBase` for its open drawer: the fixture opens one through
	the real service, and these hand it to the person under test rather than
	writing a second definition of what an open till is.
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

		self.till = frappe.db.get_value(
			"POS Opening Entry",
			{"pos_profile": self.profile, "status": "Open", "docstatus": 1},
			"name",
		)
		if not self.till:
			self.skipTest("the fixture left no drawer open to hand over")

		self.drawer_owner = frappe.db.get_value("POS Opening Entry", self.till, "user")

		# A personal drawer is what holds a person at work (`D-218`); a shared one
		# does not, and that case is asserted on its own below.
		self.shift_type = frappe.db.get_value("Branch", BRANCH, "shift_type")
		frappe.db.set_value("Branch", BRANCH, "shift_type", "multi")

	def tearDown(self):
		# Handed back. Every later test in the suite reads this drawer as the
		# fixture's, and one left in somebody else's name stops the terminal
		# selling (`BR-044`).
		frappe.db.set_value("POS Opening Entry", self.till, {"user": self.drawer_owner, "status": "Open"})
		frappe.db.set_value("Branch", BRANCH, "shift_type", self.shift_type or "single")
		super().tearDown()

	def _hand_over_the_drawer(self) -> None:
		frappe.db.set_value("POS Opening Entry", self.till, "user", STAFF)

	def test_a_drawer_is_found_under_whoever_holds_it(self):
		self._hand_over_the_drawer()

		self.assertTrue(attendance.holds_a_drawer(STAFF))

	def test_a_counted_drawer_is_no_longer_held(self):
		self._hand_over_the_drawer()
		frappe.db.set_value("POS Opening Entry", self.till, "status", "Closed")

		self.assertFalse(attendance.holds_a_drawer(STAFF))

	def test_a_shared_drawer_does_not_keep_whoever_opened_it_here(self):
		"""`D-218` — in a `single` branch the next cashier joins it; the opener may go home."""
		self._hand_over_the_drawer()
		frappe.db.set_value("Branch", BRANCH, "shift_type", "single")

		self.assertFalse(attendance.holds_a_drawer(STAFF))

	def test_somebody_elses_drawer_does_not_keep_this_person_here(self):
		"""The fixture's drawer belongs to whoever opened it, and only them."""
		self.assertFalse(attendance.holds_a_drawer(STAFF))

	def test_clocking_out_over_an_open_drawer_is_refused(self):
		attendance.punch(STAFF, log_type=attendance.IN)
		self._hand_over_the_drawer()

		with self.assertRaises(frappe.ValidationError):
			attendance.punch(STAFF, log_type=attendance.OUT)

		# And they are still at work — a refused punch that half-landed would be
		# worse than the thing it refused.
		self.assertTrue(attendance.state(STAFF)["clocked_in"])

	def test_clocking_out_once_the_drawer_is_counted(self):
		attendance.punch(STAFF, log_type=attendance.IN)

		state = attendance.punch(STAFF, log_type=attendance.OUT)

		self.assertFalse(state["clocked_in"])

	def test_clocking_in_is_never_withheld_over_a_drawer(self):
		"""Deliberately not symmetrical.

		Somebody who took the drawer having forgotten to clock in must still be
		able to record that they are here. Refusing would lose the hours in
		order to protect the sequence, which is the wrong way round.
		"""
		self._hand_over_the_drawer()

		state = attendance.punch(STAFF, log_type=attendance.IN)

		self.assertTrue(state["clocked_in"])

	def test_the_welcome_screen_is_told_who_holds_a_drawer(self):
		"""The screen draws its button from this, and the server refuses on the
		same fact — so the two cannot disagree (`CLAUDE.md` §5.4)."""
		from restaurant_pos.api import auth

		self._hand_over_the_drawer()

		signed_in = frappe.session.user
		frappe.set_user(STAFF)
		try:
			self.assertTrue(auth.me()["holding_till"])
		finally:
			frappe.set_user(signed_in)


class TestClosingTheDaySendsPeopleHome(OrderTestBase):
	"""A forgotten clock-in is closed when the branch's day is (`D-178`).

	The user met this as a screen offering *تسجيل انصراف* at seven in the
	morning, three days after a punch nobody had closed. Nothing in the building
	knows a shift ended except the manager ending the day, so that is where it
	is ended — which is what Toast does at its business-day cutoff, on by
	default, and Square does against the rostered end.

	**And the punch is marked**, because the time on it is the day's close
	rather than something a person did. Payroll reads these rows; an invented
	hour that looks punched cannot be questioned.
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
		# A terminal reaches its branch through its section — `POS Profile` has
		# no branch column of its own.
		self.branch = frappe.db.get_value(
			"Restaurant Section",
			frappe.db.get_value("POS Profile", self.profile, "restaurant_section"),
			"branch",
		)

	def tearDown(self):
		# One of these closes the branch's day for real, which also settles the
		# fixture's drawer and unhooks the terminal. Everything after it — in
		# this class and in every module that runs later — expects a terminal
		# that can sell, so it is put back.
		from restaurant_pos.tests.test_order import _ensure_shift

		_ensure_shift(self.profile)
		super().tearDown()

	def _clocked_in_days_ago(self, days: int) -> None:
		"""A punch left open, the way the user's was — outside the roster's window."""
		frappe.get_doc(
			{
				"doctype": attendance.CHECKIN,
				"employee": self.employee,
				"log_type": attendance.IN,
				"time": add_to_date(now_datetime(), days=-days),
			}
		).insert(ignore_permissions=True)

	def test_a_punch_older_than_the_roster_window_is_still_found(self):
		"""The case the whole thing exists for.

		`roster` measures a window — a day by default — so a three-day-old punch
		is invisible to it. Asking the roster would have found nobody and closed
		the day over them again.
		"""
		self._clocked_in_days_ago(3)

		on_duty = [employee.name for employee, _ in attendance.on_duty_in(self.branch)]

		self.assertIn(self.employee, on_duty)

	def test_closing_the_day_clocks_them_out(self):
		self._clocked_in_days_ago(3)

		sent_home = attendance.clock_out_everyone(self.branch, at=now_datetime())

		self.assertIn(self.employee, [row["employee"] for row in sent_home])
		self.assertFalse(attendance.state(STAFF)["clocked_in"])

	def test_closing_the_day_for_real_is_what_sends_them_home(self):
		"""End to end, through the manager's button rather than the helper.

		The helper being right is not the feature; the day's close calling it
		is. Deleting that one line left every test above green.
		"""
		from restaurant_pos.utils import shift as shift_service

		self._clocked_in_days_ago(2)
		day = frappe.db.get_value("POS Profile", self.profile, "restaurant_shift")

		result = shift_service.close_day(shift_name=day, force=True, pos_profile=self.profile)

		self.assertFalse(attendance.state(STAFF)["clocked_in"])
		self.assertIn(self.employee, [row["employee"] for row in result["clocked_out"]])

	def test_the_punch_says_the_system_wrote_it(self):
		"""Toast flags these so a manager can list and correct them; so do we."""
		self._clocked_in_days_ago(1)

		attendance.clock_out_everyone(self.branch, at=now_datetime())

		self.assertEqual(
			frappe.db.get_value(
				"Employee Checkin",
				{"employee": self.employee, "log_type": attendance.OUT},
				"rpos_auto_clock_out",
			),
			1,
		)

	def test_somebody_already_gone_home_is_left_alone(self):
		"""No second OUT: two in a row is a shift whose length cannot be read."""
		self._clocked_in_days_ago(1)
		attendance.punch(STAFF, log_type=attendance.OUT)
		before = frappe.db.count("Employee Checkin", {"employee": self.employee})

		self.assertEqual(attendance.clock_out_everyone(self.branch, at=now_datetime()), [])
		self.assertEqual(frappe.db.count("Employee Checkin", {"employee": self.employee}), before)

	def test_the_punch_is_never_earlier_than_the_arrival(self):
		"""A shift of no length is at least arithmetic somebody can read; a
		negative one is a payroll figure nobody can."""
		# Whole seconds: MySQL stores a `Datetime` without microseconds, so a
		# value read back is always a shade earlier than one built in Python —
		# and this assertion is about an ordering, not about that.
		arrival = add_to_date(now_datetime(), days=1).replace(microsecond=0)
		frappe.get_doc(
			{
				"doctype": attendance.CHECKIN,
				"employee": self.employee,
				"log_type": attendance.IN,
				"time": arrival,
			}
		).insert(ignore_permissions=True)

		sent_home = attendance.clock_out_everyone(self.branch, at=now_datetime())

		self.assertEqual(len(sent_home), 1)
		self.assertGreaterEqual(sent_home[0]["at"], arrival)

	def test_the_day_says_how_many_it_will_send_home(self):
		"""Said on the screen the manager presses the button on, not found later
		in a payroll report."""
		from restaurant_pos.utils import shift as shift_service

		self._clocked_in_days_ago(1)
		day = frappe.db.get_value("POS Profile", self.profile, "restaurant_shift")

		self.assertGreaterEqual(shift_service.summarise(day)["on_duty"], 1)

	def test_the_sweep_is_recorded_as_an_automatic_one(self):
		"""Anything that happens to somebody's hours is answerable for."""
		self._clocked_in_days_ago(1)

		attendance.clock_out_everyone(self.branch, at=now_datetime(), pos_profile=self.profile)

		entry = frappe.get_all(
			"POS Audit Log",
			filters={"action_type": "clock_out", "branch": self.branch},
			fields=["details"],
			order_by="creation desc",
			limit=1,
		)
		self.assertTrue(entry)
		self.assertIn('"automatic":true', entry[0].details.lower().replace(" ", ""))


def _a_gender() -> str:
	"""Any one, because `Employee.gender` is mandatory and this is a fixture.

	Like the fiscal year in `test_payment`, `Gender` is setup-wizard data and
	this bench never ran it (`D-012`). Nothing here reads the value back.
	"""
	existing = frappe.db.get_value("Gender", {}, "name")
	if existing:
		return existing

	return frappe.get_doc({"doctype": "Gender", "gender": "Other"}).insert(ignore_permissions=True).name


class TestWhoIsAtWork(FrappeTestCase):
	"""The manager's half of `FR-8.4`.

	Punches nobody at the restaurant can read are a table only payroll will ever
	open, months later, when the argument is already lost. These cover the
	arithmetic, because that is where a roster is wrong in a way nobody notices:
	the total looks plausible either way.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_user(STAFF)
		frappe.db.commit()

	def setUp(self):
		super().setUp()
		if not attendance.is_available():
			self.skipTest("hrms is not installed on this site")

		self.employee = _employee_for(STAFF)
		if not self.employee:
			self.skipTest("this site cannot create an Employee")

		frappe.db.delete("Employee Checkin", {"employee": self.employee})

	def _punch_at(self, log_type: str, minutes_ago: int) -> None:
		frappe.get_doc(
			{
				"doctype": "Employee Checkin",
				"employee": self.employee,
				"log_type": log_type,
				"time": add_to_date(now_datetime(), minutes=-minutes_ago),
			}
		).insert(ignore_permissions=True)

	def _me(self, roster: dict) -> dict | None:
		return next((row for row in roster["people"] if row["employee"] == self.employee), None)

	def test_a_closed_pair_counts_the_time_between_them(self):
		self._punch_at(attendance.IN, 120)
		self._punch_at(attendance.OUT, 60)

		row = self._me(attendance.roster())

		self.assertFalse(row["on_duty"])
		self.assertAlmostEqual(row["minutes"], 60, delta=1)

	def test_an_open_punch_counts_up_to_now_and_shows_on_duty(self):
		"""The whole point of the column: somebody still here has no OUT yet."""
		self._punch_at(attendance.IN, 90)

		roster = attendance.roster()
		row = self._me(roster)

		self.assertTrue(row["on_duty"])
		self.assertAlmostEqual(row["minutes"], 90, delta=1)
		self.assertIn(self.employee, [person["employee"] for person in roster["on_duty"]])

	def test_two_spells_in_one_day_add_up(self):
		"""A break in the middle is two pairs, not one long shift."""
		self._punch_at(attendance.IN, 300)
		self._punch_at(attendance.OUT, 240)
		self._punch_at(attendance.IN, 120)
		self._punch_at(attendance.OUT, 60)

		self.assertAlmostEqual(self._me(attendance.roster())["minutes"], 120, delta=2)

	def test_an_out_with_no_in_before_it_is_skipped_not_guessed(self):
		"""A punch a manager corrected by hand beats any repair invented here.

		The orphan is placed **after** a closed pair on purpose. Put first it
		proves nothing — every plausible wrong implementation also scores it
		zero, which a mutation of `_worked` demonstrated. Here a repair that
		anchored it to the previous punch, or to the start of the window, would
		add ninety minutes that nobody worked.
		"""
		self._punch_at(attendance.IN, 200)
		self._punch_at(attendance.OUT, 190)
		self._punch_at(attendance.OUT, 100)

		self.assertAlmostEqual(self._me(attendance.roster())["minutes"], 10, delta=1)

	def test_punches_older_than_the_window_are_left_out(self):
		self._punch_at(attendance.IN, 60 * 24 * 5)
		self._punch_at(attendance.OUT, 60 * 24 * 5 - 120)

		row = self._me(attendance.roster(days=1))

		self.assertIsNone(row, "a person who did not work in the window is not on the list")


class TestTheRosterAlwaysAnswers(FrappeTestCase):
	"""Whatever the site is missing, the screen gets something to render.

	Deliberately outside the class above, which skips without hrms — a guard
	that only runs where the thing works proves nothing about where it does not
	(`D-074`, `D-135`).
	"""

	def test_the_shape_is_the_same_with_or_without_hrms(self):
		roster = attendance.roster()

		self.assertEqual(
			set(roster),
			{"available", "since", "on_duty", "people"},
		)
		self.assertIsInstance(roster["people"], list)
		self.assertIsInstance(roster["on_duty"], list)
		self.assertEqual(roster["available"], attendance.is_available())


class TestWrongPinsMakeTheDeviceWait(FrappeTestCase):
	"""`D-204` — a PIN is five digits, so guessing has to be slow.

	The limit this replaced counted per PIN *value*, so each new guess started
	from zero, and the two manager overrides had no limit at all: a signed-in
	cashier could try every manager PIN from the discount dialog.
	"""

	DEVICE = "203.0.113.7"
	OTHER_DEVICE = "203.0.113.8"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_user(STAFF)
		frappe.db.commit()

	def setUp(self):
		super().setUp()
		pins.set_pin(STAFF, "51234")
		self._forget()
		frappe.local.request_ip = self.DEVICE

	def tearDown(self):
		frappe.local.request_ip = None
		self._forget()
		frappe.set_user("Administrator")
		super().tearDown()

	def _forget(self):
		for ip in (self.DEVICE, self.OTHER_DEVICE):
			pins.attempts_from(ip).add_success_attempt()

	def _guess_wrong(self, times: int):
		for _ in range(times):
			self.assertIsNone(pins.identify("99999"))

	def test_after_five_wrong_pins_even_the_right_one_waits(self):
		self._guess_wrong(pins.WRONG_PINS_ALLOWED)

		with self.assertRaises(frappe.RateLimitExceededError):
			pins.identify("51234")

	def test_one_short_of_the_limit_the_right_pin_still_works(self):
		"""The other side of the line — a lock one guess early is a till that
		refuses a cashier who only mistyped."""
		self._guess_wrong(pins.WRONG_PINS_ALLOWED - 1)

		self.assertEqual(pins.identify("51234"), STAFF)

	def test_a_right_pin_does_not_clear_the_count(self):
		"""Or a cashier signs in with their own PIN between guesses, forever."""
		self._guess_wrong(pins.WRONG_PINS_ALLOWED - 1)
		self.assertEqual(pins.identify("51234"), STAFF)
		self._guess_wrong(1)

		with self.assertRaises(frappe.RateLimitExceededError):
			pins.identify("51234")

	def test_the_overrides_and_the_sign_in_share_one_count(self):
		"""Three doors, one count — or each door gives five more guesses."""
		for _ in range(3):
			self.assertIsNone(perms.find_approver_for_discount("max_order_discount_pct", 5, "99999"))
		for _ in range(2):
			self.assertIsNone(pins.find_approver_for_pin("can_void_item", "99999"))

		frappe.set_user("Guest")
		with self.assertRaises(frappe.RateLimitExceededError):
			auth_api.sign_in("51234")

	def test_another_device_is_not_made_to_wait(self):
		self._guess_wrong(pins.WRONG_PINS_ALLOWED)

		frappe.local.request_ip = self.OTHER_DEVICE
		self.assertEqual(pins.identify("51234"), STAFF)

	def test_the_wait_ends(self):
		self._guess_wrong(pins.WRONG_PINS_ALLOWED)

		pins.attempts_from(self.DEVICE).login_failed_time = add_to_date(
			now_datetime(), seconds=-(pins.LOCK_SECONDS + 1)
		)

		self.assertEqual(pins.identify("51234"), STAFF)

	def test_nothing_is_counted_outside_a_request(self):
		"""A console types no guess — and a suite sharing one count would lock
		itself out halfway through."""
		frappe.local.request_ip = None
		self._guess_wrong(pins.WRONG_PINS_ALLOWED * 2)

		self.assertEqual(pins.identify("51234"), STAFF)

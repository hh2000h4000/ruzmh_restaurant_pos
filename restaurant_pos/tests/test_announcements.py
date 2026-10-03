# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Announcements from the office to the tills (`D-303`).

Who receives one, that reading it is recorded per person, and that the bell
pages it together with the tickets that did not print.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from restaurant_pos.tests.test_order import BRANCH, CASHIER, _make_cashier
from restaurant_pos.utils import announcements, bell

SENIOR = "rpos_announcement_senior@example.com"


def _senior() -> str:
	if not frappe.db.exists("User", SENIOR):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": SENIOR,
				"first_name": "RPOS Announcement Senior",
				"send_welcome_email": 0,
				"roles": [{"role": "POS Senior Cashier"}],
			}
		).insert(ignore_permissions=True)
	return SENIOR


def _draft(**audience):
	doc = frappe.get_doc(
		{
			"doctype": "POS Announcement",
			"subject": "Shawarma is out today",
			"message": "Do not sell it until tomorrow.",
			"urgent": audience.pop("urgent", 0),
			"expires_on": audience.pop("expires_on", None),
			"branches": [{"branch": branch} for branch in audience.get("branches", [])],
			"roles": [{"role": role} for role in audience.get("roles", [])],
			"users": [{"user": user} for user in audience.get("users", [])],
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


def _sent(**audience):
	doc = _draft(**audience)
	doc.submit()
	return doc


class AnnouncementTestBase(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_make_cashier()
		_senior()


class WhoReceivesIt(AnnouncementTestBase):
	def test_nothing_chosen_reaches_everyone_at_a_till(self):
		people = announcements.recipients(_draft())

		self.assertIn(CASHIER, people)
		self.assertIn(SENIOR, people)

	def test_only_people_named_reach_only_them(self):
		"""A note to one cashier is not a note to the restaurant because nothing else was ticked."""
		self.assertEqual(announcements.recipients(_draft(users=[CASHIER])), [CASHIER])

	def test_a_role_narrows_it(self):
		people = announcements.recipients(_draft(roles=["POS Senior Cashier"]))

		self.assertIn(SENIOR, people)
		self.assertNotIn(CASHIER, people)

	def test_a_branch_leaves_out_who_works_elsewhere_and_keeps_who_works_anywhere(self):
		def restricted(user):
			return {"RPOS Elsewhere"} if user == CASHIER else None

		with patch.object(announcements, "allowed_branches", side_effect=restricted):
			people = announcements.recipients(_draft(branches=[BRANCH]))

		self.assertNotIn(CASHIER, people)
		self.assertIn(SENIOR, people)

	def test_people_named_are_added_to_a_narrowed_audience(self):
		people = announcements.recipients(_draft(roles=["POS Senior Cashier"], users=[CASHIER]))

		self.assertEqual({CASHIER, SENIOR} - set(people), set())


class SendingIt(AnnouncementTestBase):
	def test_sending_fixes_who_receives_it_and_says_when_and_who_sent_it(self):
		doc = _sent(users=[CASHIER, SENIOR])

		self.assertEqual(sorted(row.user for row in doc.recipients), sorted([CASHIER, SENIOR]))
		self.assertTrue(doc.sent_at)
		self.assertEqual(doc.sent_by, frappe.session.user)
		self.assertIn("2", doc.read_count)

	def test_an_announcement_nobody_would_receive_is_refused(self):
		doc = _draft()

		with (
			patch.object(announcements, "recipients", return_value=[]),
			self.assertRaises(frappe.ValidationError),
		):
			doc.submit()


class ReadingIt(AnnouncementTestBase):
	def _mine(self, user, doc):
		return next((row for row in announcements.mine(user, 50) if row["key"] == doc.name), None)

	def test_reading_is_recorded_for_the_reader_alone(self):
		doc = _sent(users=[CASHIER, SENIOR])
		before = announcements.unread(CASHIER)

		announcements.mark_read(CASHIER, doc.name)

		self.assertTrue(self._mine(CASHIER, doc)["read"])
		self.assertFalse(self._mine(SENIOR, doc)["read"])
		self.assertEqual(announcements.unread(CASHIER), before - 1)
		self.assertIn("1", frappe.db.get_value("POS Announcement", doc.name, "read_count"))

	def test_all_at_once(self):
		_sent(users=[CASHIER])
		_sent(users=[CASHIER])

		announcements.mark_read(CASHIER)

		self.assertEqual(announcements.unread(CASHIER), 0)

	def test_a_withdrawn_or_expired_one_leaves_the_bell(self):
		withdrawn = _sent(users=[CASHIER])
		withdrawn.cancel()
		expired = _sent(users=[CASHIER], expires_on=add_days(nowdate(), -1))
		today = _sent(users=[CASHIER], expires_on=nowdate())

		self.assertIsNone(self._mine(CASHIER, withdrawn))
		self.assertIsNone(self._mine(CASHIER, expired))
		self.assertIsNotNone(self._mine(CASHIER, today))

	def test_it_reaches_only_who_it_was_sent_to(self):
		doc = _sent(users=[SENIOR])

		self.assertIsNone(self._mine(CASHIER, doc))


class TheBellListsBoth(AnnouncementTestBase):
	def test_newest_first_whichever_kind(self):
		older = {"kind": "print", "key": "KOT-OLD", "at": "2000-01-01 00:00:00"}
		doc = _sent(users=[CASHIER], urgent=1)

		with patch.object(bell.kitchen, "print_alerts", return_value=[older]):
			items = bell.feed("any branch", CASHIER)["items"]

		keys = [item["key"] for item in items]
		self.assertLess(keys.index(doc.name), keys.index("KOT-OLD"))
		self.assertTrue(next(item for item in items if item["key"] == doc.name)["urgent"])

	def test_the_badge_counts_this_cashiers_unread(self):
		_sent(users=[CASHIER])

		with patch.object(bell.kitchen, "print_alerts", return_value=[]):
			self.assertEqual(
				bell.feed("any branch", CASHIER)["unread_announcements"], announcements.unread(CASHIER)
			)


OFFICE = "rpos_announcement_office@example.com"
STRANGER = "rpos_announcement_stranger@example.com"


def _desk_user(email: str) -> str:
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"roles": [{"role": "Stock User"}],
			}
		).insert(ignore_permissions=True)
	return email


class TheOfficeHearsItInERPNextsBell(AnnouncementTestBase):
	"""The user: «ليش ما نستخدم نظام الإشعارات في ERPNext» — so the desk's own bell rings too."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_desk_user(OFFICE)
		_desk_user(STRANGER)

	def _logs(self, doc, user):
		return frappe.get_all(
			"Notification Log",
			filters={"for_user": user, "document_type": "POS Announcement", "document_name": doc.name},
			fields=["name", "read", "type"],
		)

	def test_someone_in_the_desk_gets_it_in_erpnexts_bell_and_a_cashier_does_not(self):
		doc = _sent(users=[OFFICE, CASHIER])

		office = self._logs(doc, OFFICE)
		self.assertEqual(len(office), 1)
		self.assertEqual(office[0].type, "Alert")  # Alert sends no email
		self.assertEqual(self._logs(doc, CASHIER), [])

	def test_reading_it_anywhere_clears_erpnexts_bell(self):
		doc = _sent(users=[OFFICE])

		announcements.mark_read(OFFICE, doc.name)

		self.assertEqual(self._logs(doc, OFFICE)[0].read, 1)

	def test_who_it_was_sent_to_may_open_it_and_nobody_else_in_the_desk(self):
		doc = _sent(users=[OFFICE])
		doc.reload()

		self.assertTrue(announcements.has_permission(doc, "read", OFFICE))
		self.assertFalse(announcements.has_permission(doc, "write", OFFICE))
		self.assertFalse(announcements.has_permission(doc, "read", STRANGER))
		self.assertTrue(announcements.has_permission(doc, "read", "Administrator"))

	def test_the_desk_list_shows_a_recipient_only_what_was_sent_to_them(self):
		self.assertIn(frappe.db.escape(OFFICE), announcements.query_conditions(OFFICE))
		self.assertIsNone(announcements.query_conditions("Administrator"))

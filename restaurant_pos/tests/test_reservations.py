# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Reservations: a time on a table, not a colour painted on it.

**The clock is fixed at six in the evening** of the day the suite runs. A
booking is a date and a time, and a suite that took "now plus three hours" at
ten at night would put it on tomorrow and fail for a reason that has nothing to
do with the code. The service reads the moment through one name, and that is
the one patched.

Refs: BR-090..BR-094, FR-14.1..FR-14.4, D-191
"""

import random
from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_to_date, get_datetime, getdate, now_datetime

from restaurant_pos.api import reservation as api
from restaurant_pos.api import table as table_api
from restaurant_pos.tests.test_order import ITEM, free_table
from restaurant_pos.tests.test_payment import CASH, PaymentTestBase
from restaurant_pos.utils import order as orders
from restaurant_pos.utils import payment
from restaurant_pos.utils import reservation as service

DOCTYPE = "Restaurant Reservation"
TURN = 90
GRACE = 15


def _phone() -> str:
	"""A number nobody else in the suite has, so no booking links to a stranger."""
	return f"05{random.randint(10_000_000, 99_999_999)}"


class ReservationTestBase(PaymentTestBase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.branch = frappe.db.get_value("Restaurant Section", cls.section, "branch")
		cls.tables = frappe.get_all(
			"Restaurant Table",
			filters={"section": cls.section, "is_active": 1},
			pluck="name",
			order_by="table_number asc",
			limit=3,
		)
		frappe.db.set_value(
			"Branch", cls.branch, {"reservation_turn_minutes": TURN, "reservation_grace_minutes": GRACE}
		)
		frappe.clear_document_cache("Branch", cls.branch)
		frappe.db.commit()

	def setUp(self):
		self.now = get_datetime(f"{getdate(now_datetime())} 18:00:00")
		patcher = patch("restaurant_pos.utils.reservation.now_datetime", return_value=self.now)
		self.clock = patcher.start()
		self.addCleanup(patcher.stop)

		for table in self.tables:
			free_table(table)
		# Bookings an earlier test left on these tables would clash with this one.
		for name in frappe.get_all(DOCTYPE, filters={"table": ("in", self.tables)}, pluck="name"):
			frappe.db.set_value(DOCTYPE, name, "status", "cancelled")

	def _move_clock(self, minutes: int) -> None:
		self.clock.return_value = add_to_date(self.now, minutes=minutes)

	def _book(self, minutes: int = 60, table: str | None = "first", party: int = 2, **extra) -> str:
		at = add_to_date(self.now, minutes=minutes)
		return service.save(
			{
				"customer_name": "RPOS Guest",
				"phone": _phone(),
				"party_size": party,
				"reservation_date": str(at.date()),
				"reservation_time": at.strftime("%H:%M:%S"),
				"table": self.tables[0] if table == "first" else table,
				**extra,
			},
			branch=self.branch,
		)["reservation"]

	def _on_floor(self, table: str):
		plan = table_api.get_floor_plan(self.section)
		return next(row for row in plan["tables"] if row.name == table)

	def _seat(self, name: str) -> dict:
		return service.seat(name, pos_profile=self.profile, order_type=self.dine_in)


class TestTheFloor(ReservationTestBase):
	def test_a_table_is_held_from_one_turn_before_the_booking(self):
		"""A walk-in seated any later would still be eating when the party came."""
		self._book(minutes=60)

		table = self._on_floor(self.tables[0])

		self.assertEqual(table.status, "reserved")
		self.assertTrue(table.reservation["held"])
		self.assertEqual(table.reservation["party_size"], 2)

	def test_further_off_the_booking_is_only_a_note(self):
		"""The table works for walk-ins until the hold begins."""
		self._book(minutes=TURN + 60)

		table = self._on_floor(self.tables[0])

		self.assertEqual(table.status, "available")
		self.assertFalse(table.reservation["held"])

	def test_after_the_grace_period_the_table_is_the_floors_again(self):
		name = self._book(minutes=60)
		self._move_clock(60 + GRACE + 5)

		table = self._on_floor(self.tables[0])

		self.assertEqual(table.status, "available")
		self.assertIsNone(table.reservation)
		late = next(row for row in service.listing(self.branch) if row.name == name)
		self.assertEqual(late.phase, "late")

	def test_people_at_the_table_keep_it_occupied_and_the_booking_is_a_note(self):
		"""The host needs to know table four is due back at eight."""
		self._book(minutes=60)
		orders.create_order(
			order_type=self.dine_in, pos_profile=self.profile, table=self.tables[0], cover_count=2
		)

		table = self._on_floor(self.tables[0])

		self.assertEqual(table.status, "occupied")
		self.assertIsNotNone(table.reservation)

	def test_the_table_itself_is_never_stored_as_reserved(self):
		"""Derived each time the floor is read — nothing to forget to clear."""
		self._book(minutes=60)

		self.assertEqual(frappe.db.get_value("Restaurant Table", self.tables[0], "status"), "available")

	def test_inside_the_grace_period_the_table_is_still_held(self):
		"""Ten minutes late is late, not gone — the common practice is fifteen."""
		self._book(minutes=60)
		self._move_clock(60 + GRACE - 5)

		self.assertEqual(self._on_floor(self.tables[0]).status, "reserved")

	def test_a_table_with_a_bill_on_it_is_never_painted_reserved(self):
		"""Occupancy is read from the bills, not the stored status (`BR-066`).

		Every path that seats a bill marks the table occupied, so this is the
		case where the two have drifted apart — a table carrying people and still
		stored as available. Painting it yellow would tell the host it is free
		for the party at eight.
		"""
		self._book(minutes=60)
		orders.create_order(
			order_type=self.dine_in, pos_profile=self.profile, table=self.tables[0], cover_count=2
		)
		frappe.db.set_value("Restaurant Table", self.tables[0], "status", "available")

		table = self._on_floor(self.tables[0])

		self.assertNotEqual(table.status, "reserved")
		self.assertTrue(table.orders)

	def test_a_table_left_marked_reserved_with_no_booking_reads_free(self):
		"""A stored `reserved` from before is not a booking, and a yellow table
		with nothing behind it is a lie."""
		frappe.db.set_value("Restaurant Table", self.tables[0], "status", "reserved")

		self.assertEqual(self._on_floor(self.tables[0]).status, "available")


class TestTheRules(ReservationTestBase):
	def test_a_second_booking_within_one_turn_is_refused(self):
		"""Both cannot be honoured: the second party finds the first still eating."""
		self._book(minutes=60)

		with self.assertRaises(frappe.ValidationError):
			self._book(minutes=60 + TURN - 30)

	def test_one_turn_apart_is_fine(self):
		self._book(minutes=60)
		self._book(minutes=60 + TURN)

	def test_another_table_at_the_same_time_is_fine(self):
		self._book(minutes=60)
		self._book(minutes=60, table=self.tables[1])

	def test_a_time_already_past_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._book(minutes=-(GRACE + 10))

	def test_a_party_bigger_than_the_table_is_warned_not_refused(self):
		capacity = frappe.db.get_value("Restaurant Table", self.tables[0], "capacity") or 4
		at = add_to_date(self.now, minutes=60)

		result = service.save(
			{
				"customer_name": "RPOS Big Party",
				"phone": _phone(),
				"party_size": capacity + 2,
				"reservation_date": str(at.date()),
				"reservation_time": at.strftime("%H:%M:%S"),
				"table": self.tables[0],
			},
			branch=self.branch,
		)

		self.assertTrue(frappe.db.exists(DOCTYPE, result["reservation"]))
		self.assertTrue(result["warnings"])

	def test_a_booking_taken_at_the_till_is_confirmed_and_names_who_took_it(self):
		doc = frappe.get_doc(DOCTYPE, self._book())

		self.assertEqual(doc.status, "confirmed")
		self.assertTrue(doc.created_by_name)

	def test_a_known_number_arrives_as_the_customer(self):
		"""The same search the customer box runs (`D-050`) — and nobody is created."""
		from restaurant_pos.utils import customer

		phone = _phone()
		known = customer.create(phone=phone, customer_name="RPOS Regular")["name"]
		at = add_to_date(self.now, minutes=60)

		name = service.save(
			{
				"customer_name": "RPOS Regular",
				"phone": phone,
				"party_size": 2,
				"reservation_date": str(at.date()),
				"reservation_time": at.strftime("%H:%M:%S"),
			},
			branch=self.branch,
		)["reservation"]

		self.assertEqual(frappe.db.get_value(DOCTYPE, name, "customer"), known)

	def test_a_booking_no_longer_expected_cannot_be_changed(self):
		name = self._book()
		service.cancel(name, "changed their plans")

		with self.assertRaises(frappe.ValidationError):
			service.save(
				{"name": name, "customer_name": "X", "phone": _phone(), "party_size": 2}, branch=self.branch
			)


class TestSeating(ReservationTestBase):
	def test_seating_opens_the_bill_with_what_the_booking_knew(self):
		"""Toast does this: seating a party pre-opens its check on the POS."""
		name = self._book(minutes=30, party=3, notes="window seat, a birthday")

		result = self._seat(name)

		order = frappe.get_doc("Restaurant Order", result["order_name"])
		self.assertEqual(order.table, self.tables[0])
		self.assertEqual(order.cover_count, 3)
		self.assertEqual(order.call_name, "RPOS Guest")
		self.assertEqual(order.reservation, name)
		self.assertIn("birthday", order.notes or "")

		booking = frappe.get_doc(DOCTYPE, name)
		self.assertEqual(booking.status, "seated")
		self.assertEqual(booking.restaurant_order, order.name)
		self.assertTrue(booking.seated_at)

		story = frappe.get_all("POS Order Activity", filters={"restaurant_order": order.name}, pluck="action")
		self.assertIn("reservation_seated", story)

	def test_a_booking_for_another_day_is_not_seated_today(self):
		at = add_days(add_to_date(self.now, minutes=60), 1)
		name = service.save(
			{
				"customer_name": "RPOS Tomorrow",
				"phone": _phone(),
				"party_size": 2,
				"reservation_date": str(at.date()),
				"reservation_time": at.strftime("%H:%M:%S"),
				"table": self.tables[0],
			},
			branch=self.branch,
		)["reservation"]

		with self.assertRaises(frappe.ValidationError):
			self._seat(name)

	def test_paying_the_bill_completes_the_booking(self):
		name = self._book(minutes=30)
		order = frappe.get_doc("Restaurant Order", self._seat(name)["order_name"])
		orders.add_item(order, item=ITEM)
		order.reload()

		payment.process_payment(order, payments=[{"method": CASH, "amount": order.total_amount}])

		self.assertEqual(frappe.db.get_value(DOCTYPE, name, "status"), "completed")

	def test_a_seated_booking_is_not_cancelled(self):
		name = self._book(minutes=30)
		self._seat(name)

		with self.assertRaises(frappe.ValidationError):
			service.cancel(name, "too late for that")


class TestCancelAndNoShow(ReservationTestBase):
	def test_cancelling_needs_a_reason(self):
		name = self._book()

		with self.assertRaises(frappe.ValidationError):
			service.cancel(name, "  ")

		service.cancel(name, "the guest called")
		self.assertEqual(frappe.db.get_value(DOCTYPE, name, "status"), "cancelled")

	def test_a_no_show_before_its_time_is_refused(self):
		name = self._book(minutes=60)

		with self.assertRaises(frappe.ValidationError):
			service.no_show(name)

		self._move_clock(70)
		service.no_show(name)
		self.assertEqual(frappe.db.get_value(DOCTYPE, name, "status"), "no_show")
		self.assertFalse(frappe.db.get_value(DOCTYPE, name, "auto_no_show"))

	def test_closing_the_day_marks_the_forgotten_and_flags_them(self):
		"""`D-178`'s reasoning: only the person closing the day knows it is over."""
		missed = self._book(minutes=60)
		tonight = self._book(minutes=5 * 60, table=self.tables[1])

		marked = service.close_out(self.branch, at=add_to_date(self.now, minutes=60 + GRACE + 10))

		self.assertGreaterEqual(marked, 1)
		self.assertEqual(frappe.db.get_value(DOCTYPE, missed, "status"), "no_show")
		self.assertEqual(frappe.db.get_value(DOCTYPE, missed, "auto_no_show"), 1)
		# Later than the close — still expected, left alone.
		self.assertEqual(frappe.db.get_value(DOCTYPE, tonight, "status"), "confirmed")


NOBODY = "rpos_no_till_role@example.com"


class TestTheEndpoints(ReservationTestBase):
	def test_somebody_with_no_till_role_is_refused(self):
		if not frappe.db.exists("User", NOBODY):
			frappe.get_doc(
				{"doctype": "User", "email": NOBODY, "first_name": "RPOS Nobody", "send_welcome_email": 0}
			).insert(ignore_permissions=True)

		frappe.set_user(NOBODY)
		try:
			with self.assertRaises(frappe.PermissionError):
				api.list_reservations(pos_profile=self.profile)
		finally:
			frappe.set_user("Administrator")

	def test_a_replayed_booking_is_taken_once(self):
		at = add_to_date(self.now, minutes=60)
		payload = {
			"customer_name": "RPOS Twice",
			"phone": _phone(),
			"party_size": 2,
			"reservation_date": str(at.date()),
			"reservation_time": at.strftime("%H:%M:%S"),
			"table": self.tables[2],
		}
		queue_id = frappe.generate_hash(length=16)

		first = api.save_reservation(pos_profile=self.profile, reservation=payload, queue_id=queue_id)
		second = api.save_reservation(pos_profile=self.profile, reservation=payload, queue_id=queue_id)

		self.assertEqual(first["reservation"], second["reservation"])
		self.assertEqual(frappe.db.count(DOCTYPE, {"customer_name": "RPOS Twice", "status": "confirmed"}), 1)

	def test_the_list_is_in_the_order_guests_arrive(self):
		later = self._book(minutes=4 * 60, table=self.tables[1])
		sooner = self._book(minutes=60)

		names = [row.name for row in api.list_reservations(pos_profile=self.profile)]

		self.assertLess(names.index(sooner), names.index(later))

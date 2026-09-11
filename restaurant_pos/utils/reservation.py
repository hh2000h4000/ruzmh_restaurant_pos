# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Reservations: a time on a table, not a colour painted on it (FR-14, D-191).

**A table is never stored as reserved.** `Restaurant Table.status` has a
`reserved` value and nothing ever set it; set by hand, it would hold a table
all day for a booking at eight in the evening and stay yellow until somebody
remembered to clear it. So the floor reads the day's bookings each time it is
drawn and works the hold out — the way it reads occupancy from the open bills
rather than from a field somebody updates (`BR-066`).

**One number decides the hold: how long a table is expected to be used.**
Toast and SevenRooms plan seating on turn times (a couple about an hour and a
half); a table is held from that long before the booking, because a walk-in
seated any later would still be eating when the booked party arrives. The same
number refuses a second booking on the same table too close to the first. A
separate "turn yellow an hour before" window was considered and dropped: it
would let a walk-in sit seventy minutes before an eight o'clock booking and
collide with it anyway.

**And a grace period for the late**, fifteen minutes by default — the common
practice. After it the table goes back to the floor; the booking stays expected
until the day is closed, which records it as a no-show.

Refs: BR-090..BR-094, FR-14.1..FR-14.4, D-191
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, getdate, now_datetime

DOCTYPE = "Restaurant Reservation"

#: Still expected: somebody is coming.
EXPECTED = ("pending", "confirmed")

#: Minutes, when a branch has not set its own (`D-191`).
DEFAULT_TURN = 90
DEFAULT_GRACE = 15


# --------------------------------------------------------------------------- #
# Time
# --------------------------------------------------------------------------- #


def settings(branch: str | None) -> tuple[int, int]:
	"""The branch's turn time and grace period, in minutes."""
	row = (
		frappe.get_cached_value(
			"Branch", branch, ["reservation_turn_minutes", "reservation_grace_minutes"], as_dict=True
		)
		if branch
		else None
	) or {}

	turn = cint(row.get("reservation_turn_minutes")) or DEFAULT_TURN
	grace = row.get("reservation_grace_minutes")
	# Zero is a real answer here — "we give the table away on the minute" — so
	# only an unset value falls back.
	return turn, (DEFAULT_GRACE if grace in (None, "") else cint(grace))


def when(row):
	"""The moment the party is expected."""
	return get_datetime(f"{getdate(row.reservation_date)} {row.reservation_time}")


def phase(row, now, turn: int, grace: int) -> str:
	"""Where an expected booking stands: ``upcoming``, ``held`` or ``late``.

	``held`` runs from one turn before the booking to the end of the grace
	period after it — the stretch in which seating anybody else at that table
	collides with the party that booked it.
	"""
	at = when(row)
	if now < add_to_date(at, minutes=-turn):
		return "upcoming"
	if now <= add_to_date(at, minutes=grace):
		return "held"
	return "late"


# --------------------------------------------------------------------------- #
# The floor
# --------------------------------------------------------------------------- #


def on_the_floor(tables: list, branch: str) -> None:
	"""Hang the day's next expected booking on each table (`FR-14.2`).

	One query for the section, like the bills beside it: the floor redraws on
	every change. A late booking is left off — its table is the floor's again —
	and appears on the reservations list instead.

	A table with a held booking and nobody at it **reads as reserved**. One with
	people at it stays occupied and carries the booking as a note, because the
	host needs to know table four is due back at eight.
	"""
	for table in tables:
		table.reservation = None
		# Nothing sets a stored `reserved` any more; one left from before is not
		# a booking, and a yellow table with nothing behind it is a lie.
		if table.status == "reserved":
			table.status = "available"

	names = [table.name for table in tables]
	if not names:
		return

	now = now_datetime()
	rows = frappe.get_all(
		DOCTYPE,
		filters={
			"table": ("in", names),
			"status": ("in", EXPECTED),
			"reservation_date": getdate(now),
		},
		fields=["name", "table", "customer_name", "party_size", "reservation_date", "reservation_time"],
		order_by="reservation_time asc",
	)
	if not rows:
		return

	turn, grace = settings(branch)
	first: dict[str, tuple] = {}
	for row in rows:
		state = phase(row, now, turn, grace)
		if state != "late":
			first.setdefault(row.table, (row, state))

	for table in tables:
		hit = first.get(table.name)
		if not hit:
			continue

		row, state = hit
		table.reservation = {
			"name": row.name,
			"guest": row.customer_name,
			"party_size": cint(row.party_size),
			"time": str(row.reservation_time)[:5],
			"held": state == "held",
		}
		if state == "held" and table.status == "available" and not table.get("orders"):
			table.status = "reserved"


# --------------------------------------------------------------------------- #
# The rules on the record itself
# --------------------------------------------------------------------------- #


def validate(doc) -> None:
	"""Called by the DocType's own `validate`, so the desk obeys the same rules."""
	if doc.table:
		table = frappe.db.get_value("Restaurant Table", doc.table, ["section", "is_active"], as_dict=True)
		if not table:
			frappe.throw(_("Table {0} does not exist.").format(doc.table))

		doc.section = doc.section or table.section
		branch = frappe.db.get_value("Restaurant Section", table.section, "branch")
		if doc.branch and branch != doc.branch:
			frappe.throw(_("Table {0} is not in this branch.").format(doc.table))

	if doc.status not in EXPECTED:
		return

	turn, grace = settings(doc.branch)

	# A booking entered after its own time has passed is a typing slip, not a
	# plan: nobody can arrive for it.
	if doc.is_new() and add_to_date(when(doc), minutes=grace) < now_datetime():
		frappe.throw(_("That time has already passed."))

	assert_no_clash(doc, turn)


def assert_no_clash(doc, turn: int) -> None:
	"""Refuse a second booking on the same table within one turn of another.

	Both cannot be honoured: whichever party arrives second finds the first
	still eating. Different tables, or the same table far enough apart, are
	fine.
	"""
	if not doc.table:
		return

	at = when(doc)
	for other in frappe.get_all(
		DOCTYPE,
		filters={
			"table": doc.table,
			"reservation_date": getdate(doc.reservation_date),
			"status": ("in", (*EXPECTED, "seated")),
			"name": ("!=", doc.name or ""),
		},
		fields=["name", "customer_name", "reservation_date", "reservation_time"],
	):
		gap = abs((when(other) - at).total_seconds()) / 60
		if gap < turn:
			frappe.throw(
				_("Table {0} is already booked at {1} for {2}.").format(
					frappe.db.get_value("Restaurant Table", doc.table, "table_number") or doc.table,
					str(other.reservation_time)[:5],
					other.customer_name,
				)
			)


def warnings(doc) -> list[str]:
	"""What the host should hear but may still go ahead with."""
	said = []
	if doc.table:
		capacity = cint(frappe.db.get_value("Restaurant Table", doc.table, "capacity"))
		if capacity and cint(doc.party_size) > capacity:
			said.append(
				_("Table {0} seats {1}; the party is {2}.").format(
					frappe.db.get_value("Restaurant Table", doc.table, "table_number"),
					capacity,
					doc.party_size,
				)
			)
	return said


# --------------------------------------------------------------------------- #
# What the host does
# --------------------------------------------------------------------------- #


def listing(branch: str, day=None) -> list[dict]:
	"""A day's reservations for a branch, in the order the guests arrive."""
	day = getdate(day) if day else getdate(now_datetime())
	now = now_datetime()
	turn, grace = settings(branch)

	rows = frappe.get_all(
		DOCTYPE,
		filters={"branch": branch, "reservation_date": day},
		fields=[
			"name",
			"customer_name",
			"phone",
			"party_size",
			"customer",
			"reservation_date",
			"reservation_time",
			"section",
			"table",
			"status",
			"restaurant_order",
			"notes",
			"cancel_reason",
			"auto_no_show",
			"created_by_name",
		],
		order_by="reservation_time asc, creation asc",
	)

	numbers = dict(
		frappe.get_all(
			"Restaurant Table",
			filters={"name": ("in", [row.table for row in rows if row.table] or [""])},
			fields=["name", "table_number"],
			as_list=True,
		)
	)

	for row in rows:
		row.time = str(row.reservation_time)[:5]
		row.table_number = numbers.get(row.table)
		row.phase = phase(row, now, turn, grace) if row.status in EXPECTED else None
		row.reservation_date = str(row.reservation_date)
		row.reservation_time = row.time

	return rows


def save(data: dict, *, branch: str) -> dict:
	"""Take a booking, or change one that is still expected (`FR-14.1`)."""
	name = data.get("name")
	doc = frappe.get_doc(DOCTYPE, name) if name else frappe.new_doc(DOCTYPE)

	if name:
		if doc.branch != branch:
			frappe.throw(_("Reservation {0} is not in this branch.").format(name))
		if doc.status not in EXPECTED:
			frappe.throw(_("This reservation is {0} and can no longer be changed.").format(_(doc.status)))

	phone = (data.get("phone") or "").strip()
	doc.update(
		{
			"customer_name": (data.get("customer_name") or "").strip(),
			"phone": phone,
			"party_size": cint(data.get("party_size")),
			"reservation_date": data.get("reservation_date"),
			"reservation_time": data.get("reservation_time"),
			"table": data.get("table") or None,
			"section": data.get("section") or None,
			"notes": (data.get("notes") or "").strip() or None,
			"customer": data.get("customer") or doc.customer or _customer_by_phone(phone),
		}
	)

	if not name:
		doc.branch = branch
		# **Taken at the till is confirmed.** The guest is on the phone or at the
		# counter; there is nobody left to confirm it with. `pending` is kept for
		# a booking that arrives by itself — an online request — which is what
		# the status was written for.
		doc.status = "confirmed"
		doc.created_by_name = (
			frappe.db.get_value("User", frappe.session.user, "full_name") or frappe.session.user
		)

	if not doc.customer_name:
		frappe.throw(_("A name is required."))
	if not phone:
		frappe.throw(_("A mobile number is required."))

	doc.save(ignore_permissions=True) if name else doc.insert(ignore_permissions=True)
	return {"reservation": doc.name, "warnings": warnings(doc)}


def _customer_by_phone(phone: str) -> str | None:
	"""The customer this number already belongs to, if any (`D-050`).

	The same search the till's customer box runs, so a regular who books by
	phone arrives at the table already known — history, points and all — and
	nobody is created: a booking is not a reason to file a person.
	"""
	if not phone:
		return None

	from restaurant_pos.utils import customer

	found = customer.search(phone=phone, limit=1)
	return found[0]["name"] if found else None


def seat(name: str, *, pos_profile: str, order_type: str, table: str | None = None) -> dict:
	"""The party has arrived: open their bill at their table (`FR-14.3`).

	Toast does exactly this — seating a party pre-opens its check on the POS —
	and so the order carries what the booking already knew: the guests, the
	name to call, the special requests, and the customer when the number
	matched one.
	"""
	from restaurant_pos.utils import activity
	from restaurant_pos.utils import order as orders

	doc = frappe.get_doc(DOCTYPE, name)
	if doc.status not in EXPECTED:
		frappe.throw(_("This reservation is {0} and can no longer be changed.").format(_(doc.status)))

	if getdate(doc.reservation_date) != getdate(now_datetime()):
		frappe.throw(_("This reservation is for {0}, not today.").format(doc.reservation_date))

	table = table or doc.table
	if not table:
		frappe.throw(_("Choose a table for this reservation first."))

	order = orders.create_order(
		order_type=order_type,
		pos_profile=pos_profile,
		table=table,
		customer=doc.customer,
		cover_count=doc.party_size,
		call_name=doc.customer_name,
		notes=doc.notes,
	)
	order.db_set("reservation", doc.name, update_modified=False)

	doc.status = "seated"
	doc.table = table
	doc.restaurant_order = order.name
	doc.seated_at = now_datetime()
	doc.save(ignore_permissions=True)

	activity.log(
		order,
		"reservation_seated",
		subject=doc.customer_name,
		details={"reservation": doc.name, "party_size": cint(doc.party_size), "booked_for": str(when(doc))},
	)

	return {"order_name": order.name, "reservation": doc.name}


def cancel(name: str, reason: str) -> dict:
	"""`FR-14.4` — any status still expected, with a reason."""
	doc = _expected(name)
	if not (reason or "").strip():
		frappe.throw(_("Cancel Reason is required when a reservation is cancelled."))

	doc.status = "cancelled"
	doc.cancel_reason = reason.strip()
	doc.save(ignore_permissions=True)
	return {"reservation": doc.name, "status": doc.status}


def no_show(name: str) -> dict:
	"""The party did not come — said once their time has come, never before it."""
	doc = _expected(name)
	if now_datetime() < when(doc):
		frappe.throw(_("A guest cannot miss a reservation before its time."))

	doc.status = "no_show"
	doc.save(ignore_permissions=True)
	return {"reservation": doc.name, "status": doc.status}


def _expected(name: str):
	doc = frappe.get_doc(DOCTYPE, name)
	if doc.status not in EXPECTED:
		frappe.throw(_("This reservation is {0} and can no longer be changed.").format(_(doc.status)))
	return doc


def complete(order) -> None:
	"""The seated party paid: the booking is done (`BR-091`)."""
	if order.get("reservation") and frappe.db.get_value(DOCTYPE, order.reservation, "status") == "seated":
		frappe.db.set_value(DOCTYPE, order.reservation, "status", "completed", update_modified=False)


def close_out(branch: str, *, at) -> int:
	"""Record every booking nobody came for as a no-show, when the day closes.

	The manager closing the day is the one moment the building knows the
	evening is over — the same reasoning that sends forgotten clock-ins home
	(`D-178`). **Marked `auto_no_show`**: a guest's record of missed bookings is
	something a restaurant may act on, and one written by the system has to be
	told apart from one a host saw happen.
	"""
	_, grace = settings(branch)
	marked = 0

	for row in frappe.get_all(
		DOCTYPE,
		filters={
			"branch": branch,
			"status": ("in", EXPECTED),
			"reservation_date": ("<=", getdate(at)),
		},
		fields=["name", "reservation_date", "reservation_time"],
	):
		# A booking later than the close — tonight after midnight, say — is
		# still expected and is left alone.
		if add_to_date(when(row), minutes=grace) > get_datetime(at):
			continue

		frappe.db.set_value(
			DOCTYPE, row.name, {"status": "no_show", "auto_no_show": 1}, update_modified=False
		)
		marked += 1

	return marked

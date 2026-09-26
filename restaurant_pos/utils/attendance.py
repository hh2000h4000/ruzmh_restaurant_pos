# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Clocking in and out — a person's hours, not a drawer.

**Deliberately nothing to do with the till shift** (`FR-8.4`, `D-057`). A shift
is a cash drawer and its count; a clock-in is somebody's working time. They come
apart constantly: under ``shift_type = single`` a cashier joining a colleague
opens no drawer at all, and a waiter never opens one — yet both are at work and
both have to be paid.

**One exception, and only one** (`D-177`): a clock-*out* is refused while the
person still holds an open drawer. Separate records, but going home is one gate
— see `holds_a_drawer`.

Built on ERPNext's own `Employee Checkin` and `Employee`, so the punches land
where payroll already looks for them rather than in a table only this app knows
about.

Refs: FR-8.4, D-057, D-094
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime, time_diff_in_seconds

from restaurant_pos.utils.audit import log_audit

IN, OUT = "IN", "OUT"


def employee_for(user: str) -> str | None:
	"""The Employee record a login belongs to, if there is one.

	Not everyone who can sign in is an employee — an administrator or an
	integration user is not — so this is allowed to come back empty. Signing in
	still works; only the attendance buttons go away.
	"""
	return frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")


def last_punch(employee: str) -> frappe._dict | None:
	return frappe.db.get_value(
		"Employee Checkin",
		{"employee": employee},
		["name", "log_type", "time"],
		as_dict=True,
		order_by="time desc, creation desc",
	)


def state(user: str) -> dict:
	"""Whether this person is currently clocked in, and since when.

	`time desc` rather than `creation desc`: a punch corrected by an
	administrator carries the time it should have had, and the question here is
	about the working day, not about data entry.
	"""
	employee = employee_for(user) if is_available() else None
	if not employee:
		return {"employee": None, "clocked_in": False, "since": None}

	punch = last_punch(employee)
	clocked_in = bool(punch and punch.log_type == IN)

	return {
		"employee": employee,
		"employee_name": frappe.db.get_value("Employee", employee, "employee_name"),
		"clocked_in": clocked_in,
		"since": punch.time if clocked_in else None,
	}


#: Where the punches live, and the app they come from.
CHECKIN = "Employee Checkin"


def is_available() -> bool:
	"""Whether this site can record attendance at all (`D-135`).

	`hooks.required_apps` names hrms so a fresh install cannot miss it, but a
	site installed before that declaration will not have it — and the symptom
	there is silence: `frappe.db.get_value` answers `None` on an absent table
	rather than raising, so the screen offers a button that throws.
	"""
	return bool(frappe.db.exists("DocType", CHECKIN))


def roster(branch: str | None = None, *, days: int = 1) -> dict:
	"""Who is at work, and how long each of them has worked (`FR-8.4`).

	The manager's half of attendance, and the half that makes recording it worth
	anything: punches nobody at the restaurant can read are a table only payroll
	will ever open, months later, when the argument is already lost.

	**Hours are computed from the punches in the window, in order.** An `IN`
	still open when the window ends counts up to now — that is the whole point
	of the "on duty" column — and an `OUT` with no `IN` before it is skipped
	rather than guessed at, because a punch a manager corrected by hand is more
	trustworthy than any repair this could invent.

	Scoped by branch through the `Employee` record. An employee with no branch
	set is shown to everyone: a restaurant that never filled the field would
	otherwise see an empty screen and conclude the feature is broken.
	"""
	if not is_available():
		return {"available": False, "since": None, "on_duty": [], "people": []}

	since = add_to_date(now_datetime(), days=-max(int(days or 1), 1))

	employees = staff_of(branch)

	by_name = {row.name: row for row in employees}
	if not by_name:
		return {"available": True, "since": since, "on_duty": [], "people": []}

	punches = frappe.get_all(
		CHECKIN,
		filters={"employee": ("in", list(by_name)), "time": (">=", since)},
		fields=["employee", "log_type", "time"],
		order_by="employee asc, time asc",
		limit_page_length=0,
	)

	people = [_worked(by_name[name], rows) for name, rows in _by_employee(punches).items()]
	people.sort(key=lambda row: (not row["on_duty"], -row["minutes"]))

	return {
		"available": True,
		"since": since,
		"on_duty": [row for row in people if row["on_duty"]],
		"people": people,
	}


def staff_of(branch: str | None) -> list:
	"""The active employees a branch's screens speak for.

	**An employee with no branch set belongs to everyone.** A restaurant that
	never filled the field would otherwise see an empty roster and conclude the
	feature is broken — and, since `clock_out_everyone` reads the same list, its
	staff would be left on the clock for the same silent reason.

	One definition, because the roster and the day's close have to agree about
	who works here (`CLAUDE.md` §5.5).
	"""
	employees = frappe.get_all(
		"Employee",
		filters={"status": "Active"},
		fields=["name", "employee_name", "branch"],
		limit_page_length=0,
	)
	if not branch:
		return employees

	return [row for row in employees if not row.branch or row.branch == branch]


def _by_employee(punches) -> dict[str, list]:
	grouped: dict[str, list] = {}
	for row in punches:
		grouped.setdefault(row.employee, []).append(row)
	return grouped


def _worked(employee, punches, until=None) -> dict:
	"""Minutes between each IN and the OUT that follows it.

	An `IN` still open counts up to ``until`` — now, on the roster; the end of
	the period, on the hours report (`D-274`), so a shift still running today
	does not pad last month.
	"""
	minutes = 0.0
	started = None

	for row in punches:
		if row.log_type == IN:
			started = row.time
		elif started:
			minutes += time_diff_in_seconds(row.time, started) / 60
			started = None

	if started:
		minutes += max(time_diff_in_seconds(until or now_datetime(), started), 0) / 60

	return {
		"employee": employee.name,
		"employee_name": employee.employee_name,
		"on_duty": bool(started),
		"since": started,
		"minutes": int(minutes),
	}


def on_duty_in(branch: str | None) -> list[tuple]:
	"""Everyone whose last punch was a clock-in — however long ago (`D-178`).

	**Deliberately not `roster`'s answer.** That one measures a window, a day by
	default, and computes hours inside it; a punch older than the window is
	invisible to it. The stale clock-in this was written for is precisely the
	punch that falls outside — the user's was three days old — so asking the
	roster would have found nobody and closed the day over them again.

	The question here has no window: what was this person's last punch, and was
	it an arrival. One definition, read by the day's summary and by the sweep
	that acts on it (`CLAUDE.md` §5.5).
	"""
	if not is_available():
		return []

	standing = []
	for employee in staff_of(branch):
		punch = last_punch(employee.name)
		if punch and punch.log_type == IN:
			standing.append((employee, punch))

	return standing


def clock_out_everyone(branch: str, *, at, pos_profile: str | None = None) -> list[dict]:
	"""Send home whoever is still on the clock when the branch's day ends (`D-178`).

	**Why this exists.** A clock-in nothing ever closes stays open forever. The
	user met it as a screen offering *تسجيل انصراف* at seven in the morning,
	three days after a punch they had forgotten — the app was telling the truth
	and the truth was useless. Nothing in the building knows the shift ended
	except the manager closing the day, so that is where it is closed.

	**This is what the reference systems do.** Toast clocks out everyone still
	in at the business-day cutoff, on by default. Square offers the same tied to
	the rostered end. Lightspeed leaves it to a manager's edit — and that is the
	behaviour we had, which is how a punch survived three days.

	**And the punch is marked as ours.** `rpos_auto_clock_out` says the time is
	the day's close rather than something a person did, because payroll reads
	these rows and an invented hour that looks punched cannot be questioned.
	Toast flags them for exactly this and lets a manager list and correct them;
	so does the desk list, which is where a marked row is visible.

	**Never fatal.** A day has to be closable. A record that will not save is
	logged and skipped rather than stranding the close — the failure belongs in
	the error log, not in front of a manager at two in the morning.

	Returns what it did, so the screen can say so rather than acting silently.
	"""
	sent_home = []
	for employee, punch in on_duty_in(branch):
		try:
			sent_home.append(_close_the_punch(employee, punch, at, pos_profile))
		except Exception:
			# Named, so the log says which person was left on the clock.
			frappe.log_error(f"Could not clock {employee.name} out with the day", "RPOS attendance")
			continue

		# **Audited separately, and that is not tidiness.** Written together,
		# an audit row that would not save discarded a punch that already had —
		# the person was clocked out and reported as not clocked out. Two
		# failures with different consequences deserve two answers: one loses
		# somebody's hours, the other loses the record of who ended them.
		try:
			log_audit(
				"clock_out",
				branch=branch,
				pos_profile=pos_profile,
				details={"employee": employee.name, "automatic": True},
			)
		except Exception:
			frappe.log_error(
				f"Clocked {employee.name} out with the day but could not record it",
				"RPOS attendance",
			)

	return sent_home


def _close_the_punch(employee, punch, at, pos_profile: str | None) -> dict:
	"""One automatic OUT.

	Never earlier than the punch it closes: a clock-in made after the moment the
	day is being closed for would otherwise produce negative hours, and a shift
	of no length is at least arithmetic somebody can read.
	"""
	when = at if at >= punch.time else punch.time

	frappe.get_doc(
		{
			"doctype": CHECKIN,
			"employee": employee.name,
			"log_type": OUT,
			"time": when,
			"device_id": pos_profile,
			"rpos_auto_clock_out": 1,
		}
	).insert(ignore_permissions=True)

	return {"employee": employee.name, "employee_name": employee.employee_name, "at": when}


def holds_a_drawer(user: str):
	"""The till this person still has open somewhere, or ``None`` (`D-177`).

	**The till itself, not a yes** (`D-218`): the refusal has to say *which* one.
	"Close your till" to somebody standing at a terminal whose drawer is closed —
	theirs is open at another branch — is a true sentence that sends them nowhere.

	**The one place hours and drawers touch**, and the docstring at the top of
	this module says why they otherwise do not. A cash drawer is money somebody
	is answerable for; going home is the moment that answerability ends. Letting
	a cashier clock out over an open drawer leaves a count nobody made against a
	person who is no longer at work — which is exactly the case a shortage is
	meant to be traceable through.

	It is the order the user described: open the till, work, close the till,
	*then* clock out. Every till of consequence enforces it — Toast refuses the
	clock-out and names the open shift.

	The clock-*in* is not gated the same way, on purpose. Somebody who opened a
	drawer having forgotten to clock in must still be able to record that they
	are here; refusing would lose the hours to protect a sequence.

	Imported here rather than at the top, following `utils/order.py`: `shift`
	pulls in half the app, and this module is loaded on every sign-in.
	"""
	from restaurant_pos.utils.shift import held_till

	return held_till(user)


def punch(user: str, *, log_type: str, pos_profile: str | None = None) -> dict:
	"""Record one clock-in or clock-out.

	Refuses to repeat the direction it is already in. Two INs in a row is not a
	harmless duplicate — it is a shift whose length cannot be computed, and it
	is what a cashier produces by pressing a button twice when the first press
	seemed not to respond.
	"""
	if not is_available():
		# Named rather than raw: a cashier meeting `DoesNotExistError` learns
		# nothing, and the person who can fix it is not in the room.
		frappe.throw(_("Attendance needs the HR app. Ask an administrator to install it."))

	employee = employee_for(user)
	if not employee:
		frappe.throw(_("This login is not linked to an employee record."))

	current = state(user)
	if log_type == IN and current["clocked_in"]:
		frappe.throw(_("You are already clocked in."))
	if log_type == OUT and not current["clocked_in"]:
		frappe.throw(_("You are not clocked in."))
	held = holds_a_drawer(user) if log_type == OUT else None
	if held:
		from restaurant_pos.utils.shift import till_opened_at

		frappe.throw(
			_("Your till on {0} has been open since {1}. Close it before clocking out.").format(
				held.pos_profile, till_opened_at(held)
			)
		)

	checkin = frappe.get_doc(
		{
			"doctype": "Employee Checkin",
			"employee": employee,
			"log_type": log_type,
			"time": now_datetime(),
			# Which terminal it happened at, for the manager reading it back.
			"device_id": pos_profile,
		}
	)
	checkin.insert(ignore_permissions=True)

	return state(user)

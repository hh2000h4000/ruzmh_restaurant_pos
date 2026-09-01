# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Clocking in and out — a person's hours, not a drawer.

**Deliberately nothing to do with the till shift** (`FR-8.4`, `D-057`). A shift
is a cash drawer and its count; a clock-in is somebody's working time. They come
apart constantly: under ``shift_type = single`` a cashier joining a colleague
opens no drawer at all, and a waiter never opens one — yet both are at work and
both have to be paid.

Built on ERPNext's own `Employee Checkin` and `Employee`, so the punches land
where payroll already looks for them rather than in a table only this app knows
about.

Refs: FR-8.4, D-057, D-094
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime

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
	employee = employee_for(user)
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


def punch(user: str, *, log_type: str, pos_profile: str | None = None) -> dict:
	"""Record one clock-in or clock-out.

	Refuses to repeat the direction it is already in. Two INs in a row is not a
	harmless duplicate — it is a shift whose length cannot be computed, and it
	is what a cashier produces by pressing a button twice when the first press
	seemed not to respond.
	"""
	employee = employee_for(user)
	if not employee:
		frappe.throw(_("This login is not linked to an employee record."))

	current = state(user)
	if log_type == IN and current["clocked_in"]:
		frappe.throw(_("You are already clocked in."))
	if log_type == OUT and not current["clocked_in"]:
		frappe.throw(_("You are not clocked in."))

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

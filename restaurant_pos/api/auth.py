# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Signing in at the till with a PIN, and clocking in and out.

A cashier does not type an email address and a password between customers, and a
till in kiosk mode raises no keyboard to type them with. So the ERPNext login
screen is replaced by a numeric pad, and the PIN *is* the login (`D-094`).

**The PIN logs the person in for real.** It does not select a name on top of a
shared session: `frappe.session.user` becomes them, so every permission check,
every `POS Audit Log` row and every "whose drawer is this" question keeps working
exactly as it did — none of that code knows a PIN exists.

Refs: FR-8.4, FR-12.2, D-057, D-094
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

from restaurant_pos.utils import attendance, manager_pin
from restaurant_pos.utils.audit import log_audit

#: Attempts per minute from one address before it is refused.
#:
#: Five digits is 100,000 combinations, and this endpoint has to be reachable
#: without a session — a locked till has nobody signed in to authorise the
#: unlocking. The limit is what makes the arithmetic hopeless: at this rate a
#: full sweep takes years, and the audit log fills up long before.
ATTEMPTS_PER_MINUTE = 10


@frappe.whitelist(allow_guest=True)
@rate_limit(key="pin", limit=ATTEMPTS_PER_MINUTE, seconds=60)
def sign_in(pin: str, pos_profile: str | None = None) -> dict:
	"""Sign in with a PIN. Returns who it is and whether they are clocked in.

	`allow_guest` because a locked terminal has no session: whoever just walked
	up is exactly who this has to identify. That is why the rate limit above is
	not optional.
	"""
	pin = (pin or "").strip()

	user = manager_pin.find_user_by_pin(pin) if pin.isdigit() else None
	if not user or not frappe.db.get_value("User", user, "enabled") or not _may_use_the_till(user):
		_record_failure(pos_profile)
		# One message for a wrong PIN, a disabled account, and a PIN belonging to
		# somebody with no business at a till. Distinguishing them would tell an
		# attacker which guesses were close.
		frappe.throw(_("That PIN was not recognised."), frappe.AuthenticationError)

	frappe.local.login_manager.login_as(user)

	return me(pos_profile=pos_profile)


@frappe.whitelist()
def sign_out() -> dict:
	"""Leave the till locked, with nobody signed in.

	A real logout, not a screen that hides the buttons: the session goes, so a
	terminal left on the sign-in screen has no rights at all until the next PIN.
	"""
	frappe.local.login_manager.logout()
	frappe.db.commit()

	return {"signed_out": True}


@frappe.whitelist()
def me(pos_profile: str | None = None) -> dict:
	"""Who is signed in, and their attendance — what the welcome screen shows."""
	user = frappe.session.user
	full_name = frappe.db.get_value("User", user, "full_name") or user

	return {
		"user": user,
		"full_name": full_name,
		"pos_profile": pos_profile,
		"attendance": attendance.state(user),
		"pin_length": manager_pin.PIN_LENGTH,
	}


@frappe.whitelist()
def clock_in(pos_profile: str | None = None) -> dict:
	"""FR-8.4 — start of a person's working time, not of a drawer."""
	return _punch(attendance.IN, pos_profile)


@frappe.whitelist()
def clock_out(pos_profile: str | None = None) -> dict:
	return _punch(attendance.OUT, pos_profile)


def _may_use_the_till(user: str) -> bool:
	"""Whether this login has any business at a point of sale.

	A PIN is not a master key — the same rule `find_approver_for_pin` follows
	for overrides. Without this, **any** enabled account with a PIN could sign
	in: the print agent's own service user has one available to it, and so does
	every back-office login. They would arrive at a till that then refused them
	everything, which reads as a broken terminal rather than as a refusal.

	An RPOS role is the test, because that is what the permission sets hang off.
	"""
	from restaurant_pos.utils.permissions import get_pos_permission_set

	return bool(get_pos_permission_set(user).get("roles"))


def _branch_of(pos_profile: str | None) -> str | None:
	"""A terminal's branch, reached through its Restaurant Section."""
	if not pos_profile:
		return None

	section = frappe.db.get_value("POS Profile", pos_profile, "restaurant_section")
	return frappe.db.get_value("Restaurant Section", section, "branch") if section else None


def _punch(log_type: str, pos_profile: str | None) -> dict:
	state = attendance.punch(frappe.session.user, log_type=log_type, pos_profile=pos_profile)

	branch = _branch_of(pos_profile)
	if branch:
		log_audit(
			"clock_in" if log_type == attendance.IN else "clock_out",
			branch=branch,
			pos_profile=pos_profile,
			details={"employee": state.get("employee")},
		)

	return state


def _record_failure(pos_profile: str | None) -> None:
	"""A refused PIN is recorded; **the PIN itself never is** (`CLAUDE.md` §5.4).

	Written as Administrator because there is no session yet — that nobody was
	identified is the whole content of the event.

	Falls back to the error log when the terminal is unknown, because
	`POS Audit Log` requires a branch and a run of refused PINs from a terminal
	that has not been set up is exactly the run worth seeing.
	"""
	branch = _branch_of(pos_profile)
	try:
		frappe.set_user("Administrator")
		if branch:
			log_audit("pin_sign_in_failed", branch=branch, pos_profile=pos_profile)
		else:
			frappe.log_error(f"Refused PIN from an unknown terminal: {pos_profile}", "RPOS auth")
		frappe.db.commit()
	except Exception:
		# Failing to record must not change the message the person at the
		# counter sees, or the failure becomes a way to probe for valid PINs.
		frappe.log_error("Could not record a failed PIN sign-in", "RPOS auth")
	finally:
		frappe.set_user("Guest")

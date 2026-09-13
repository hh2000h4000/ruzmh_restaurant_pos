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
import frappe.sessions
from frappe import _

from restaurant_pos.utils import attendance, manager_pin
from restaurant_pos.utils.audit import log_audit


@frappe.whitelist(allow_guest=True)
def sign_in(pin: str, pos_profile: str | None = None) -> dict:
	"""Sign in with a PIN. Returns who it is and whether they are clocked in.

	`allow_guest` because a locked terminal has no session: whoever just walked
	up is exactly who this has to identify. That is why `identify` counts wrong
	PINs per device and makes it wait (`D-204`) — five digits are only 100,000.
	"""
	pin = (pin or "").strip()

	user = manager_pin.identify(pin)

	refusal = None
	if not user:
		refusal = "no_such_pin"
	elif not frappe.db.get_value("User", user, "enabled"):
		refusal = "account_disabled"
	elif not _may_use_the_till(user):
		refusal = "no_pos_role"

	if refusal:
		# **One message for all three**, so an attacker cannot tell which guesses
		# were close. But the *reason* goes in the audit log, where only an
		# administrator sees it: without that, a PIN refused for a missing role
		# is indistinguishable from a mistyped one, and the person who set it up
		# has nothing to go on. This exact case cost time on the demo.
		_record_failure(pos_profile, reason=refusal, user=user)
		frappe.throw(_("That PIN was not recognised."), frappe.AuthenticationError)

	frappe.local.login_manager.login_as(user)

	# Mint the CSRF token now (`D-103`). `login_as` builds a session without
	# rendering a page, and it is a page render that normally issues one — so
	# without this the till signs in successfully and is refused on its first
	# write, which is the worst possible moment to discover it.
	frappe.sessions.get_csrf_token()

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
		# Whether a drawer is still theirs to count (`D-177`). The welcome screen
		# decides which attendance button to draw from it, and `punch` refuses on
		# the same fact — the screen is only saying in advance what the server
		# would answer (`CLAUDE.md` §5.4).
		"holding_till": attendance.holds_a_drawer(user),
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


def _record_failure(pos_profile: str | None, *, reason: str, user: str | None = None) -> None:
	"""A refused PIN is recorded; **the PIN itself never is** (`CLAUDE.md` §5.4).

	Written as Administrator because there is no session yet — that nobody was
	identified is the whole content of the event.

	`user` is named only when the PIN matched somebody and they were refused for
	another reason. It is not a leak: whoever reads the audit log can already
	list every user.

	Falls back to the error log when the terminal is unknown, because
	`POS Audit Log` requires a branch and a run of refused PINs from a terminal
	that has not been set up is exactly the run worth seeing.
	"""
	branch = _branch_of(pos_profile)
	details = {"reason": reason, "user": user} if user else {"reason": reason}
	try:
		frappe.set_user("Administrator")
		if branch:
			log_audit("pin_sign_in_failed", branch=branch, pos_profile=pos_profile, details=details)
		else:
			frappe.log_error(f"Refused PIN from an unknown terminal ({pos_profile}): {details}", "RPOS auth")
		frappe.db.commit()
	except Exception:
		# Failing to record must not change the message the person at the
		# counter sees, or the failure becomes a way to probe for valid PINs.
		frappe.log_error("Could not record a failed PIN sign-in", "RPOS auth")
	finally:
		frappe.set_user("Guest")

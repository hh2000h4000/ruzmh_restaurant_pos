# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""One terminal, one machine (`D-226`).

**Why a device is claimed rather than chosen from a list.** The till used to
offer every POS Profile the cashier could reach and remember the tap. Nothing
stopped a second machine from tapping the same row, and then two tills sold on
one terminal: one drawer counted twice, and receipts printing in the wrong room.

So the terminal is bound the way every serious POS binds one — the manager
issues a short code on the profile, the machine types it once, and keeps a
device token. A profile already paired is not offered to anybody else; freeing
it is a manager's act, on the profile or from the till with a manager PIN.

**The token is the machine's identity, not the cashier's.** Cashiers come and go
on the same till and sign in with their own PIN; the token says which till they
are standing at. Only its digest is stored, like the PIN and the code itself.
"""

import secrets

import frappe
from frappe import _
from frappe.utils import now_datetime

from restaurant_pos.utils import pairing
from restaurant_pos.utils.audit import log_audit

#: Room for the token to be unguessable, and short enough to sit in a browser.
TOKEN_BYTES = 32

FIELDS = (
	"rpos_device_token_hash",
	"rpos_device_name",
	"rpos_paired_at",
	"rpos_paired_by",
	"rpos_pairing_code_hash",
	"rpos_pairing_expires",
)


def issue_code(pos_profile: str) -> dict:
	"""A code for the machine that is about to become this till.

	Issuing replaces any code outstanding, and only the digest is kept — the
	code is on the screen that asked for it and nowhere else.
	"""
	doc = frappe.get_doc("POS Profile", pos_profile)
	doc.check_permission("write")
	# `D-302` — said here, not at the till: `pair` already ignores a disabled
	# terminal, and a code that can never work would send the cashier to retype it.
	if doc.disabled:
		frappe.throw(_("This terminal is disabled. Enable it before pairing a till."))

	code = pairing.new_code()
	doc.db_set(
		{
			"rpos_pairing_code_hash": pairing.digest(code),
			"rpos_pairing_expires": pairing.expires_at(),
		},
		update_modified=False,
	)

	return {
		"pos_profile": doc.name,
		"code": pairing.pretty(code),
		"minutes": pairing.PAIRING_MINUTES,
		"paired_device": doc.get("rpos_device_name"),
	}


def machine_name() -> str:
	"""What to call this machine when nobody typed a name (`D-226`).

	The cashier setting a till up should not have to invent a label: one
	terminal is one machine, so the terminal's own name is the honest default,
	and the browser it runs in is what a manager needs beside it to tell two
	apart.
	"""
	# There is no request when a script or a test pairs a till.
	agent = (frappe.get_request_header("User-Agent") if frappe.request else "") or ""
	agent = agent.lower()
	for token, label in (
		("android", "Android"),
		("iphone", "iPhone"),
		("ipad", "iPad"),
		("windows", "Windows"),
		("mac os", "Mac"),
		("linux", "Linux"),
	):
		if token in agent:
			return label
	return _("a till")


def pair(code: str, device_name: str | None = None) -> dict:
	"""Spend a code and hand this machine the terminal it names.

	Reached by a machine with nobody signed in on it, like the print agent's
	pairing (`D-212`): the till has to know which terminal it is before it can
	draw a PIN pad. The code is the authorisation, and guessing it is held to the
	PIN pad's own per-device lockout (`D-204`).

	**A paired profile is re-paired, not refused.** The manager issued a code
	for this terminal knowing it had a device; that is how a broken till is
	replaced at eight in the evening without anybody opening the office.
	"""
	tracker = pairing.guard()
	digits = pairing.digits_of(code)

	name = (
		frappe.db.get_value(
			"POS Profile",
			{
				"rpos_pairing_code_hash": pairing.digest(digits),
				"rpos_pairing_expires": (">", now_datetime()),
				"disabled": 0,
			},
		)
		if len(digits) == pairing.PAIRING_DIGITS
		else None
	)
	if not name:
		pairing.refuse(tracker)

	doc = frappe.get_doc("POS Profile", name)
	token = secrets.token_urlsafe(TOKEN_BYTES)
	# Spent before anything else happens, so a second request racing this one
	# finds nothing to match.
	doc.db_set(
		{
			"rpos_pairing_code_hash": None,
			"rpos_pairing_expires": None,
			"rpos_device_token_hash": pairing.digest(token),
			"rpos_device_name": (device_name or "").strip()[:140] or machine_name(),
			"rpos_paired_at": now_datetime(),
			# Guest when the machine pairs before anybody has signed in on it,
			# which is the ordinary case; the audit entry carries the machine.
			"rpos_paired_by": None if frappe.session.user == "Guest" else frappe.session.user,
		},
		update_modified=False,
	)
	_log(doc, "paired")

	return {"pos_profile": doc.name, "device_token": token}


def unpair(pos_profile: str) -> dict:
	"""Free the terminal: the machine holding it stops being able to sell on it."""
	doc = frappe.get_doc("POS Profile", pos_profile)
	doc.check_permission("write")

	released = doc.get("rpos_device_name")
	doc.db_set(
		{
			"rpos_device_token_hash": None,
			"rpos_device_name": None,
			"rpos_paired_at": None,
			"rpos_paired_by": None,
		},
		update_modified=False,
	)
	_log(doc, "unpaired", device=released)

	return {"pos_profile": doc.name}


def assert_this_device(profile, device_token: str | None) -> None:
	"""The gate every till session passes (`D-226`).

	Placed here rather than at each endpoint, because a check written at six
	call sites is a check missing at the seventh (`CLAUDE.md` §5.5): the session
	is what a till loads before it can do anything at all.
	"""
	held = profile.get("rpos_device_token_hash")
	if not held:
		frappe.throw(
			_("This terminal is not paired with any device yet. Ask a manager for a pairing code."),
			frappe.AuthenticationError,
		)

	if not device_token or pairing.digest(device_token) != held:
		frappe.throw(
			_("{0} is paired with another device. Ask a manager for a pairing code.").format(profile.name),
			frappe.AuthenticationError,
		)


def _log(doc, what: str, device: str | None = None) -> None:
	from restaurant_pos.utils.terminal_branch import branch_of_doc

	branch = branch_of_doc(doc)
	log_audit(
		"device_paired" if what == "paired" else "device_unpaired",
		branch=branch,
		pos_profile=doc.name,
		details={"device": device or doc.get("rpos_device_name")},
	)

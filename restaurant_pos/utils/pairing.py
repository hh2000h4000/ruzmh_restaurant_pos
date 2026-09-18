# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Short codes that bind a machine to a record, once (`D-212`, `D-226`).

Two things are paired this way — the print agent on the restaurant's computer
and the till itself — and they ask the same question: *is the machine typing
this code the one the manager meant?* So the code, its digest, its lifetime and
the lockout live here, in one place, rather than being written twice and
drifting apart at the fourth digit.

What differs is what the code buys: the agent exchanges it for API keys, the
till for a device token. That stays with each of them.
"""

import secrets

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime

#: How long a pairing code works. Long enough to walk from the desk to the
#: machine and type it; short enough that a code on a photographed screen is
#: dead by the time anybody could use it.
PAIRING_MINUTES = 10

#: Eight digits: a hundred million codes, against five wrong guesses per device
#: every five minutes, inside a ten-minute window.
PAIRING_DIGITS = 8


def new_code() -> str:
	"""A fresh code. Random, not sequential — the next one is unguessable."""
	return f"{secrets.randbelow(10**PAIRING_DIGITS):0{PAIRING_DIGITS}d}"


def expires_at():
	"""When a code issued now stops working."""
	return add_to_date(now_datetime(), minutes=PAIRING_MINUTES)


def pretty(code: str) -> str:
	"""`1234-5678` — read aloud and typed without losing one's place."""
	return f"{code[:4]}-{code[4:]}"


def digits_of(code: str | None) -> str:
	"""The code as typed, with or without its hyphen, and whatever a paste carried."""
	return "".join(character for character in (code or "") if character.isdigit())


def digest(code: str) -> str:
	"""A keyed digest, so a stolen database alone does not hand over a live code.

	The same construction as the PIN lookup (`manager_pin.lookup_of`), for the
	same reason.
	"""
	from restaurant_pos.utils.manager_pin import lookup_of

	return lookup_of(code)


def guard(scope: str = "pair"):
	"""Hold code guessing to the lockout the till's PIN pad uses (`D-204`).

	Returns the tracker so the caller can record a failure; ``None`` when the
	request carries no address to count against. Raises when this device has
	already spent its attempts.
	"""
	from restaurant_pos.utils.manager_pin import LOCK_SECONDS, attempts_from

	ip = frappe.local.request_ip
	tracker = attempts_from(ip, scope=scope) if ip else None
	if tracker and not tracker.is_user_allowed():
		frappe.throw(
			_("Too many wrong pairing codes from this device. Try again in {0} minutes.").format(
				LOCK_SECONDS // 60
			),
			frappe.RateLimitExceededError,
		)
	return tracker


def refuse(tracker) -> None:
	"""One wrong code: counted, then said in the same words whatever went wrong.

	Nothing distinguishes "no such code" from "expired" from "already used" —
	a guess learns nothing from the refusal.
	"""
	if tracker:
		tracker.add_failure_attempt()
	frappe.throw(
		_("That pairing code is not valid, or it has expired. Ask for a new one."),
		frappe.AuthenticationError,
	)

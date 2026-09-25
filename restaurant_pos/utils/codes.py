# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Codes a guest reads off a card (`D-251`, `D-260`).

**One generator, two things that need it.** A coupon code and a gift-card number
are the same object — a short string printed on a card, read down a phone, typed
at a till, and required to be unique. Coupons got it first; gift cards needed the
identical thing, and copying it would have been two alphabets to keep in step
with one `CodePad`.

**Two shapes, because they answer different worries.** Drawn codes cannot be
guessed from one another; numbered ones (`10001`, `10002`, …) can be read out,
filed and reconciled against a list the restaurant already keeps — at the price
that whoever holds one can try the next.

Refs: FR-11.1, FR-11.5, D-251, D-260
"""

from __future__ import annotations

import re
import secrets
import string

import frappe
from frappe import _

#: No `0`/`O` and no `1`/`I`/`L`: a code is read down a phone and written on a
#: card, and those are the pairs people get wrong. `CodePad` at the till offers
#: **every** character regardless, because a manager may issue any code at all
#: (`D-252`) — this is what we *draw*, not what we accept.
ALPHABET = "".join(sorted(set(string.ascii_uppercase + string.digits) - set("O0I1L")))

#: Enough that a guessing attack is not worth anybody's afternoon, short enough
#: that a guest can read it out.
CODE_LENGTH = 8

MAX_BATCH = 1000

#: What a prefix may hold. A code travels in a URL and is read down a phone, so
#: a space or a `%` in one is a support call rather than a coupon.
PREFIX = re.compile(r"^[A-Z0-9-]{0,12}$")


def make(doctype: str, *, count: int, pattern: str = "random", prefix=None, start=None) -> list[str]:
	"""`count` codes free of anything `doctype` already holds."""
	count = int(count or 0)
	if count < 1 or count > MAX_BATCH:
		frappe.throw(_("Generate between 1 and {0} at a time.").format(MAX_BATCH))

	return _numbered(doctype, prefix, start, count) if pattern == "sequential" else _drawn(doctype, count)


def _drawn(doctype: str, count: int) -> list[str]:
	"""Codes nobody can guess from one another — and never the same one twice."""
	made = []
	while len(made) < count:
		code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
		if code in made or frappe.db.exists(doctype, code):
			continue

		made.append(code)

	return made


def _numbered(doctype: str, prefix, start, count: int) -> list[str]:
	"""Codes counting up from where the restaurant's own numbering starts.

	**The starting number is text, not an integer, because its width is part of
	the answer.** Somebody who types `0001` means four digits and expects `0002`
	next; `10001` means five. Read as an integer both become the same number, and
	the leading zeros — the thing that was asked for — are gone before the first
	code is made.

	**The whole batch is refused when any code in it is taken**, naming the one
	that clashes. Skipping it the way the drawn path does would leave a hole in a
	run of numbers, and a run with a hole is worse than no run at all: whoever
	reconciles the cards against their list finds a gap and cannot tell a lost
	card from a number that was never issued.
	"""
	prefix = (prefix or "").strip().upper()
	if not PREFIX.match(prefix):
		frappe.throw(_("A prefix may hold letters, digits and dashes only, up to 12 of them."))

	start = (start or "").strip()
	if not start.isdigit():
		frappe.throw(_("Start the numbering at a number, such as 10001."))

	width = len(start)
	first = int(start)
	codes = [f"{prefix}{number:0{width}d}" for number in range(first, first + count)]

	taken = frappe.get_all(doctype, filters={"name": ("in", codes)}, pluck="name")
	if taken:
		frappe.throw(_("{0} exists already. Start the numbering somewhere else.").format(sorted(taken)[0]))

	return codes

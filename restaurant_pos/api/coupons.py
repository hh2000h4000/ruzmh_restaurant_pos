# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Issuing coupons from the desk (`D-248`, `D-251`).

**Guarded by the `POS Coupon` form's own permission**, not the till's role check
(`D-208`): this serves that desk screen, so whoever may write a coupon may
generate a batch of them, and changing the permission in the desk moves this
with it.

**Two shapes of code, because they answer different worries** (`D-251`). Drawn
codes cannot be guessed from one another; numbered ones (`10001`, `10002`, …)
can be read out, filed, and reconciled against a list the restaurant already
keeps. Cards for one company's staff want the second; a code posted publicly by
an influencer wants the first, and the form says so.

Refs: FR-11.1, D-208, D-248, D-251
"""

import re
import secrets
import string

import frappe
from frappe import _

#: No `0`/`O` and no `1`/`I`/`L`: a code is read down a phone and written on a
#: card, and those are the pairs people get wrong.
ALPHABET = "".join(sorted(set(string.ascii_uppercase + string.digits) - set("O0I1L")))

#: Enough that a guessing attack is not worth anybody's afternoon, short enough
#: that a guest can read it out.
CODE_LENGTH = 8

MAX_BATCH = 1000

#: What a prefix may hold. A code travels in a URL and is read down a phone, so
#: a space or a `%` in one is a support call rather than a coupon.
PREFIX = re.compile(r"^[A-Z0-9-]{0,12}$")


@frappe.whitelist(methods=["POST"])
def generate(
	promotion: str,
	count: int,
	campaign: str | None = None,
	max_uses: int = 1,
	pattern: str = "random",
	prefix: str | None = None,
	start: str | None = None,
) -> dict:
	"""Make `count` codes for one promotion — the batch an influencer hands out."""
	frappe.has_permission("POS Coupon", "create", throw=True)

	count = int(count or 0)
	if count < 1 or count > MAX_BATCH:
		frappe.throw(_("Generate between 1 and {0} coupons.").format(MAX_BATCH))

	if not frappe.db.exists("Restaurant Promotion", promotion):
		frappe.throw(_("Promotion {0} does not exist.").format(promotion))

	codes = _numbered(prefix, start, count) if pattern == "sequential" else _drawn(count)

	for code in codes:
		frappe.get_doc(
			{
				"doctype": "POS Coupon",
				"coupon_code": code,
				"promotion": promotion,
				"campaign": campaign,
				"max_uses": max(0, int(max_uses or 0)),
				"is_active": 1,
			}
		).insert(ignore_permissions=True)

	return {"promotion": promotion, "campaign": campaign, "codes": codes}


def _drawn(count: int) -> list[str]:
	"""Codes nobody can guess from one another — and never the same one twice."""
	made = []
	while len(made) < count:
		code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
		if code in made or frappe.db.exists("POS Coupon", code):
			continue
		made.append(code)

	return made


def _numbered(prefix: str | None, start: str | None, count: int) -> list[str]:
	"""Codes counting up from where the restaurant's own numbering starts.

	**The starting number is text, not an integer, because its width is part of
	the answer.** A manager who types `0001` means four digits and expects
	`0002` next; one who types `10001` means five. Read as an integer both
	become the same number, and the leading zeros — the thing that was asked
	for — are gone before the first code is made.

	**The whole batch is refused when any code in it is taken**, naming the one
	that clashes. Skipping it the way the drawn path does would leave a hole in
	a run of numbers, and a run with a hole is worse than no run at all: whoever
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

	taken = frappe.get_all("POS Coupon", filters={"name": ("in", codes)}, pluck="name")
	if taken:
		frappe.throw(
			_("Coupon {0} exists already. Start the numbering somewhere else.").format(sorted(taken)[0])
		)

	return codes

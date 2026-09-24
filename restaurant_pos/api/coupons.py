# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Issuing coupons from the desk (`D-248`).

**Guarded by the `POS Coupon` form's own permission**, not the till's role check
(`D-208`): this serves that desk screen, so whoever may write a coupon may
generate a batch of them, and changing the permission in the desk moves this
with it.

Refs: FR-11.1, D-208, D-248
"""

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


@frappe.whitelist(methods=["POST"])
def generate(promotion: str, count: int, campaign: str | None = None, max_uses: int = 1) -> dict:
	"""Make `count` single-use codes for one promotion — the batch an influencer hands out."""
	frappe.has_permission("POS Coupon", "create", throw=True)

	count = int(count or 0)
	if count < 1 or count > MAX_BATCH:
		frappe.throw(_("Generate between 1 and {0} coupons.").format(MAX_BATCH))

	if not frappe.db.exists("Restaurant Promotion", promotion):
		frappe.throw(_("Promotion {0} does not exist.").format(promotion))

	made = []
	while len(made) < count:
		code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
		if frappe.db.exists("POS Coupon", code):
			continue

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
		made.append(code)

	return {"promotion": promotion, "campaign": campaign, "codes": made}

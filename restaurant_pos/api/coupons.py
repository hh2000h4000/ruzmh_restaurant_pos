# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Issuing coupons from the desk (`D-248`, `D-251`).

**Guarded by the `POS Coupon` form's own permission**, not the till's role check
(`D-208`): this serves that desk screen, so whoever may write a coupon may
generate a batch of them, and changing the permission in the desk moves this
with it.

**The codes themselves come from `utils/codes`**, which gift cards use too
(`D-260`): a coupon code and a card number are the same object, and two copies
of one alphabet drift apart the first time one of them is corrected.

Refs: FR-11.1, D-208, D-248, D-251, D-260
"""

import frappe
from frappe import _

from restaurant_pos.utils import codes

#: Kept as names here because they were the published surface of this module
#: before the generator moved, and the desk script and tests read them.
ALPHABET = codes.ALPHABET
CODE_LENGTH = codes.CODE_LENGTH
MAX_BATCH = codes.MAX_BATCH


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

	if not frappe.db.exists("Restaurant Promotion", promotion):
		frappe.throw(_("Promotion {0} does not exist.").format(promotion))

	made = codes.make("POS Coupon", count=count, pattern=pattern, prefix=prefix, start=start)

	for code in made:
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

	return {"promotion": promotion, "campaign": campaign, "codes": made}

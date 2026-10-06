# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Posting the till's sales, asked for from the office (`D-317`)."""

import frappe
from frappe import _

from restaurant_pos.utils import posting as service


@frappe.whitelist(methods=["POST"])
def post_now(branch: str) -> dict:
	"""Post ``branch``'s sales now instead of at the next day close or the next hourly retry.

	In the background, as the day close does it: a branch with a week waiting
	outlasts a web request. Whoever may read the batches may ask for one — it
	does nothing the day close would not have done.
	"""
	frappe.has_permission(service.BATCH, "read", throw=True)
	if not frappe.db.exists("Branch", branch):
		frappe.throw(_("Branch {0} does not exist.").format(branch))

	service.post_now(branch)
	return {"queued": True}

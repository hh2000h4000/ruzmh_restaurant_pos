# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Whitelisted attendance endpoints — who is at work, and for how long.

Thin by design (`02_backend_rules.md`): authorise, delegate to
`utils.attendance`, return JSON. Clocking yourself in and out lives in
`api.auth`, beside the sign-in it belongs to.

Refs: FR-8.4, D-057, D-135
"""

import frappe

from restaurant_pos.utils import attendance as service
from restaurant_pos.utils.permissions import assert_permission, validate_branch_access


@frappe.whitelist()
def roster(pos_profile: str, days: int = 1) -> dict:
	"""Who is on duty now, and hours per person over the window (FR-8.4).

	Read-only, so no `queue_id`. Gated on `can_access_reports`: this answers
	"who was at work and for how long", which is a report about people — a
	cashier has no business reading their colleagues' hours, and the same flag
	already guards the day's takings.

	The branch comes from the terminal rather than the caller, so a manager
	cannot read another branch's roster by asking for it.
	"""
	assert_permission("can_access_reports")

	branch = frappe.db.get_value("POS Profile", pos_profile, "branch")
	if branch:
		validate_branch_access(branch)

	return service.roster(branch, days=int(days or 1))

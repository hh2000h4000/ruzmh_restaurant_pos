# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Reading a bill's history, and recording the two events only a screen sees.

Refs: FR-12.7, D-106
"""

from __future__ import annotations

import frappe
from frappe import _

from restaurant_pos.utils import activity as service
from restaurant_pos.utils.permissions import validate_branch_access


@frappe.whitelist()
def timeline(order_name: str) -> list[dict]:
	"""Everything that happened to one bill, oldest first.

	A **read**, so it does not go through `assert_mutable` — the history of a
	bill is exactly what somebody wants with no shift open, when they are trying
	to work out what happened last night (`D-058` drew that line).
	"""
	order = frappe.db.get_value("Restaurant Order", order_name, ["name", "branch"], as_dict=True)
	if not order:
		frappe.throw(_("Order {0} does not exist.").format(order_name))

	validate_branch_access(order.branch)

	rows = service.timeline(order_name)
	names = {row.user for row in rows}
	full_names = {user: frappe.db.get_value("User", user, "full_name") or user for user in names}

	return [row | {"user_name": full_names.get(row.user, row.user)} for row in rows]


@frappe.whitelist()
def record_view(order_name: str, action: str) -> dict:
	"""A cashier opened a held bill, or walked away from it (`D-106`).

	The only two entries the server cannot infer: nothing is written, nothing
	changes, and yet *"who had this bill open at nine o'clock"* is a question a
	manager asks about a bill that came out wrong.

	Restricted to those two actions on purpose. This endpoint is reachable from
	a till, and one that accepted any action would let a screen write whatever
	story it liked into the record.
	"""
	if action not in service.VIEW_ACTIONS:
		frappe.throw(_("{0} is not something a screen records.").format(action))

	order = frappe.db.get_value(
		"Restaurant Order", order_name, ["name", "branch", "pos_profile"], as_dict=True
	)
	if not order:
		frappe.throw(_("Order {0} does not exist.").format(order_name))

	validate_branch_access(order.branch)

	return {"entry": service.log(order, action)}

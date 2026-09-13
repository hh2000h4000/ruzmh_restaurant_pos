# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Whitelisted permission endpoints.

Thin by design (02_backend_rules.md): validate input, authorise, delegate to
``utils.permissions``, return JSON. No business logic here.

Refs: 07_API_Design.md §7, 08_Security.md §4, FR-12.3, FR-12.4, FR-12.8
"""

import frappe
from frappe import _

from restaurant_pos.utils import manager_pin as pins
from restaurant_pos.utils import permissions as perms
from restaurant_pos.utils.audit import log_audit, log_permission_change, log_refusal


@frappe.whitelist()
def get_permission_set(user: str | None = None) -> dict:
	"""Effective POS permissions, for hiding buttons in the UI.

	The frontend uses this for presentation only; every action re-validates in
	the backend (FR-12.3). Never includes the manager PIN.
	"""
	if user and user != frappe.session.user and not perms.is_superuser():
		perms.assert_permission("can_view_all_orders")

	return perms.get_pos_permission_set(user)


@frappe.whitelist()
def validate_discount_override(
	pin: str,
	percentage: float,
	reason: str,
	branch: str,
	pos_profile: str,
	order_name: str | None = None,
) -> dict:
	"""Approve a discount above the cashier's ceiling (FR-10.4, BR-031).

	Separate from :func:`validate_manager_override` because a discount is not a
	yes/no right: the approver must hold ``can_manual_promotion`` **and** have a
	ceiling that covers this percentage. Approving 90% with a 50% ceiling would
	make the ceiling decorative.

	The returned token is bound to this exact percentage.
	"""
	if not (reason or "").strip():
		frappe.throw(_("A reason is required for a discount override."))

	perms.validate_branch_access(branch)

	ceiling = "max_order_discount_pct"
	approver = perms.find_approver_for_discount(ceiling, percentage, pin)

	if not approver:
		log_refusal(
			"discount_override",
			branch=branch,
			pos_profile=pos_profile,
			restaurant_order=order_name,
			reason=reason,
			details={"percentage": percentage, "result": "rejected"},
		)
		frappe.throw(_("Invalid PIN or insufficient permissions."), frappe.PermissionError)

	log_audit(
		"discount_override",
		branch=branch,
		pos_profile=pos_profile,
		restaurant_order=order_name,
		approved_by=approver,
		reason=reason,
		details={"percentage": percentage, "result": "approved"},
	)

	return {
		"success": True,
		"approved_by": approver,
		"override_token": perms.issue_override_token(
			perms.discount_override_action(ceiling, percentage), approver
		),
	}


@frappe.whitelist()
def validate_manager_override(
	action_type: str,
	pin: str,
	reason: str,
	branch: str,
	pos_profile: str,
	order_name: str | None = None,
) -> dict:
	"""Exchange a manager PIN for a single-use override token (07 §7).

	On success the caller passes ``override_token`` to the action it was blocked
	from. On failure the response says only that it failed — never which part.
	"""
	if not (reason or "").strip():
		frappe.throw(_("A reason is required for a manager override."))

	perms.validate_branch_access(branch)

	approver = pins.find_approver_for_pin(action_type, pin)

	if not approver:
		# Logged without the attempted PIN (CLAUDE.md §5.4).
		log_refusal(
			"manager_override",
			branch=branch,
			pos_profile=pos_profile,
			restaurant_order=order_name,
			reason=reason,
			details={"action_type": action_type, "result": "rejected"},
		)
		frappe.throw(_("Invalid PIN or insufficient permissions."), frappe.PermissionError)

	log_audit(
		"manager_override",
		branch=branch,
		pos_profile=pos_profile,
		restaurant_order=order_name,
		approved_by=approver,
		reason=reason,
		details={"action_type": action_type, "result": "approved"},
	)

	return {
		"success": True,
		"approved_by": approver,
		"override_token": perms.issue_override_token(action_type, approver),
	}


# `D-201` — five endpoints stood here for a management screen that was never
# built: `list_permission_sets`, `update_permission_set`, `list_pin_holders`,
# `set_manager_pin`, `clear_manager_pin`. Nothing called them and no test
# covered them, and each was whitelisted — a door onto the most sensitive record
# in the system, standing open for a room nobody entered.
#
# Permissions are edited on the desk form and the PIN on the User form, where
# the guard now runs (`doctype/pos_permission_set`, `utils/permissions`). The
# code is in the history if a screen is ever built.

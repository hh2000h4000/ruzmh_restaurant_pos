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
from restaurant_pos.utils.audit import log_audit, log_permission_change


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
		log_audit(
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


@frappe.whitelist()
def list_permission_sets() -> list[dict]:
	"""Every role's permission set, for the management screen (FR-12.4)."""
	perms.assert_permission("can_access_reports")

	booleans, ceilings = perms.permission_fields()
	rows = []
	for role in perms.ROLE_RANK:
		if not frappe.db.exists("POS Permission Set", role):
			continue

		values = frappe.db.get_value("POS Permission Set", role, booleans + ceilings, as_dict=True)
		rows.append(
			{
				"role": role,
				"rank": perms.ROLE_RANK[role],
				"editable": perms.ROLE_RANK[role] < perms.user_rank(),
				"permissions": values,
			}
		)

	return rows


@frappe.whitelist()
def update_permission_set(role: str, values: dict, branch: str, pos_profile: str) -> dict:
	"""Apply an edit to a role's permission set (FR-12.4, FR-12.6, FR-12.7)."""
	values = frappe.parse_json(values) if isinstance(values, str) else values
	perms.validate_branch_access(branch)

	changes = perms.assert_may_edit_permission_set(role, values)
	if not changes:
		return {"changed": {}}

	doc = frappe.get_doc("POS Permission Set", role)
	for field, delta in changes.items():
		doc.set(field, delta["after"])
	doc.save(ignore_permissions=True)

	log_permission_change(target=role, changes=changes, branch=branch, pos_profile=pos_profile)

	return {"changed": changes}


@frappe.whitelist()
def list_pin_holders() -> list[dict]:
	"""Users who can approve overrides, and whether each has a PIN (FR-12.8).

	Reports only *whether* a PIN exists. The value itself is never readable.
	"""
	perms.assert_permission("can_access_reports")

	holders = set(pins.pin_holders())
	rows = []
	for user in frappe.get_all("User", filters={"enabled": 1}, pluck="name"):
		roles = perms.user_rpos_roles(user)
		if not roles:
			continue

		rows.append(
			{
				"user": user,
				"roles": roles,
				"has_pin": user in holders,
				"editable": perms.user_rank(user) < perms.user_rank() or user == frappe.session.user,
			}
		)

	return rows


@frappe.whitelist()
def set_manager_pin(user: str, pin: str, branch: str, pos_profile: str) -> dict:
	"""Set or replace a user's manager PIN (FR-12.8). Write-only.

	The PIN is never returned, never rendered, never logged — the audit entry
	records only that it changed, and for whom.
	"""
	perms.validate_branch_access(branch)
	perms.assert_may_manage_pin_of(user)

	pins.set_pin(user, pin)

	log_permission_change(
		target=user,
		changes={"pos_manager_pin": {"before": "***", "after": "***"}},
		branch=branch,
		pos_profile=pos_profile,
		reason="PIN changed",
	)

	return {"success": True}


@frappe.whitelist()
def clear_manager_pin(user: str, branch: str, pos_profile: str) -> dict:
	"""Remove a user's PIN, revoking their ability to approve overrides."""
	perms.validate_branch_access(branch)
	perms.assert_may_manage_pin_of(user)

	pins.clear_pin(user)

	log_permission_change(
		target=user,
		changes={"pos_manager_pin": {"before": "***", "after": None}},
		branch=branch,
		pos_profile=pos_profile,
		reason="PIN cleared",
	)

	return {"success": True}

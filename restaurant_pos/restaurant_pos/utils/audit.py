# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Audit trail for sensitive POS actions.

Single entry point: :func:`log_audit`. Every sensitive action goes through it,
and there is no unaudited path (FR-12.7, 08_Security.md §5).

``POS Audit Log`` is append-only, so entries are written with
``ignore_permissions`` — no role has create rights on it — and an audit failure
propagates. An action that could not be recorded must not be considered done.

Refs: 08_Security.md §5, FR-12.7, BR-013
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

# Keys whose values must never reach the audit log, matched case-insensitively
# as substrings. A PIN or token in `details` would defeat the whole point of
# never logging credentials (08 §6, CLAUDE.md §5.4).
_FORBIDDEN_KEY_PARTS = ("pin", "password", "passwd", "secret", "token", "api_key")

_REDACTED = "***"


def log_audit(
	action_type: str,
	*,
	branch: str,
	pos_profile: str,
	cashier: str | None = None,
	restaurant_order: str | None = None,
	approved_by: str | None = None,
	reason: str | None = None,
	details: dict | None = None,
) -> str:
	"""Record a sensitive action and return the log entry name.

	:param action_type: one of the options on ``POS Audit Log.action_type``
	:param branch: branch the action happened in
	:param pos_profile: terminal the action happened on
	:param cashier: defaults to the session user
	:param approved_by: the manager, when a PIN override was used
	:param details: action-specific payload; credential-looking keys are redacted
	"""
	entry = frappe.get_doc(
		{
			"doctype": "POS Audit Log",
			"timestamp": now_datetime(),
			"action_type": action_type,
			"cashier": cashier or frappe.session.user,
			"branch": branch,
			"pos_profile": pos_profile,
			"restaurant_order": restaurant_order,
			"approved_by": approved_by,
			"reason": reason,
			"details": redact(details) if details else None,
		}
	)
	entry.insert(ignore_permissions=True)
	return entry.name


def redact(value):
	"""Replace credential-looking values anywhere in a nested structure."""
	if isinstance(value, dict):
		return {key: _REDACTED if _is_forbidden(key) else redact(inner) for key, inner in value.items()}

	if isinstance(value, (list, tuple)):
		return [redact(item) for item in value]

	return value


def _is_forbidden(key) -> bool:
	lowered = str(key).lower()
	return any(part in lowered for part in _FORBIDDEN_KEY_PARTS)


def log_permission_change(
	*,
	target: str,
	changes: dict,
	branch: str,
	pos_profile: str,
	reason: str | None = None,
) -> str:
	"""Record a permission or role change with its before/after values (FR-12.7).

	:param target: the role or user whose rights changed
	:param changes: ``{fieldname: {"before": x, "after": y}}``
	"""
	if not changes:
		frappe.throw(_("A permission change must record what changed."))

	return log_audit(
		"manager_override",
		branch=branch,
		pos_profile=pos_profile,
		reason=reason,
		details={"target": target, "changes": changes},
	)

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

	# A sensitive action is also part of the bill's story (`D-106`), and it is
	# written from here so no call site has to remember two logs. Remembering it
	# at every site is how one of them gets missed, and the missed one is always
	# the interesting entry.
	if restaurant_order and action_type in _ORDER_STORY:
		from restaurant_pos.utils import activity

		activity.log(
			restaurant_order,
			_ORDER_STORY[action_type],
			subject=reason,
			details=redact(details) if details else None,
			audit_log=entry.name,
			user=cashier or frappe.session.user,
		)

	return entry.name


def log_refusal(action_type: str, **kwargs) -> str:
	"""Record a refused action so the record outlives the refusal (`D-205`).

	A refusal is written and then raised, and Frappe rolls back every request
	that raises (`frappe/app.py:154`) — so a row from `log_audit` alone vanished
	with the error it described, and a wrong manager PIN left no trace at all.

	**Rolled back first, then written, then committed.** Committing the request
	as it stood would also save whatever it wrote before failing, which is
	exactly what that rollback exists to discard.
	"""
	frappe.db.rollback()
	name = log_audit(action_type, **kwargs)
	frappe.db.commit()
	return name


#: Audit actions that belong in a bill's timeline, and what they are called
#: there. Anything absent is about a shift, a terminal or a person rather than
#: about one bill, and has no place on its story.
#:
#: **`promotion_applied` is deliberately not here** (`D-172`). The bill's story
#: already carries every offer that reached it, written where the change itself
#: happens — `RestaurantOrder.record_the_promotion` — so mapping the audit entry
#: too would put one event on the timeline twice. The audit row answers the other
#: question: *who chose it by hand*, and under which permission.
_ORDER_STORY = {
	"void_item": "item_voided",
	"bill_split": "items_moved_out",
	"bill_merged": "merged",
	"void_order": "cancelled",
	"cancel_order": "cancelled",
	"discount_applied": "discount_applied",
	"discount_override": "discount_applied",
	"price_change": "item_qty_changed",
	"payment_method_override": "paid",
	"return_created": "returned",
	"order_reopened": "opened",
	"reprint_receipt": "reprinted",
	"order_type_changed": "type_changed",
	"table_changed": "table_changed",
}


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
	branch: str | None = None,
	pos_profile: str | None = None,
	reason: str | None = None,
	action_type: str = "permission_changed",
) -> str:
	"""Record a permission or role change with its before/after values (FR-12.7).

	**Its own action type, not `manager_override`** (`D-201`): an auditor reading
	the log for approvals was reading permission edits among them, and the most
	sensitive write in the system was filed under the name of a different one.

	**And no terminal** — a permission is edited in the back office, where there
	is neither a till nor a branch. Both are optional here and on the log itself;
	every row a till writes still carries them.

	:param target: the role or user whose rights changed
	:param changes: ``{fieldname: {"before": x, "after": y}}``
	"""
	if not changes:
		frappe.throw(_("A permission change must record what changed."))

	return log_audit(
		action_type,
		branch=branch,
		pos_profile=pos_profile,
		reason=reason,
		details={"target": target, "changes": changes},
	)

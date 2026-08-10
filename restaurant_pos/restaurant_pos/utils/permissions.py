# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""POS permission resolution, branch access and manager override.

Authorisation layer 3 of 08_Security.md §1. Every whitelisted API calls into
this module before doing anything (02_backend_rules.md, FR-12.3).

The effective permission set is the *union* of the sets attached to the user's
roles: booleans are OR-ed, ceilings take the maximum. This matches how Frappe
role permissions behave everywhere else, so it is what an administrator expects
when they add a second role to a user.

Refs: 08_Security.md §§3-4, FR-12.1, FR-12.3, FR-12.6, BR-031
"""

import frappe
from frappe import _
from frappe.utils import flt
from frappe.utils.password import check_password

# Rank decides who may edit whose permissions (FR-12.6 rule 3).
ROLE_RANK = {
	"POS Cashier": 10,
	"POS Senior Cashier": 20,
	"POS Manager": 30,
	"Restaurant Manager": 40,
	"Restaurant Admin": 50,
}

RPOS_ROLES = tuple(ROLE_RANK)

# Never leave this module in a response, a log, or an error message.
SECRET_FIELDS = ("manager_pin",)

_OVERRIDE_CACHE_PREFIX = "rpos:override:"
_OVERRIDE_TTL_SECONDS = 60


# --------------------------------------------------------------------------- #
# Effective permission set
# --------------------------------------------------------------------------- #


def permission_fields() -> tuple[list[str], list[str]]:
	"""Return ``(boolean_fields, ceiling_fields)`` read from the DocType meta.

	Derived from meta rather than hardcoded so a new permission added to the
	DocType is honoured without touching this module.
	"""
	meta = frappe.get_meta("POS Permission Set")
	booleans = [f.fieldname for f in meta.fields if f.fieldtype == "Check"]
	ceilings = [f.fieldname for f in meta.fields if f.fieldtype == "Float"]
	return booleans, ceilings


def get_pos_permission_set(user: str | None = None) -> frappe._dict:
	"""Effective permissions for ``user``, merged across their RPOS roles.

	Never contains ``manager_pin``. Cached for the duration of the request.
	"""
	user = user or frappe.session.user
	cached = frappe.local.rpos_permission_cache = getattr(frappe.local, "rpos_permission_cache", {})
	if user in cached:
		return cached[user]

	booleans, ceilings = permission_fields()
	effective = frappe._dict({field: 0 for field in booleans})
	effective.update({field: 0.0 for field in ceilings})
	effective.roles = []

	for role in user_rpos_roles(user):
		if not frappe.db.exists("POS Permission Set", role):
			continue

		values = frappe.db.get_value("POS Permission Set", role, booleans + ceilings, as_dict=True)
		effective.roles.append(role)
		for field in booleans:
			effective[field] = 1 if (effective[field] or values.get(field)) else 0
		for field in ceilings:
			effective[field] = max(flt(effective[field]), flt(values.get(field)))

	# A System Manager configuring the system is not a cashier, but must not be
	# locked out of their own setup.
	if is_superuser(user):
		for field in booleans:
			effective[field] = 1
		for field in ceilings:
			effective[field] = 100.0

	for secret in SECRET_FIELDS:
		effective.pop(secret, None)

	cached[user] = effective
	return effective


def user_rpos_roles(user: str) -> list[str]:
	"""RPOS roles held by ``user``, highest rank first."""
	roles = set(frappe.get_roles(user)) & set(RPOS_ROLES)
	return sorted(roles, key=lambda role: ROLE_RANK[role], reverse=True)


def user_rank(user: str | None = None) -> int:
	"""Highest RPOS rank held by ``user``. Superusers outrank every role."""
	user = user or frappe.session.user
	if is_superuser(user):
		return max(ROLE_RANK.values())

	roles = user_rpos_roles(user)
	return ROLE_RANK[roles[0]] if roles else 0


def is_superuser(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or "System Manager" in frappe.get_roles(user)


# --------------------------------------------------------------------------- #
# Guards used by the API layer
# --------------------------------------------------------------------------- #


def assert_permission(action: str, user: str | None = None) -> None:
	"""Raise ``PermissionError`` unless ``user`` holds the boolean ``action``."""
	permissions = get_pos_permission_set(user)
	if action not in permissions:
		frappe.throw(_("Unknown POS permission: {0}").format(action))

	if not permissions[action]:
		frappe.throw(
			_("You do not have permission to perform this action."),
			frappe.PermissionError,
		)


def assert_within_discount_limit(ceiling_field: str, percentage: float, user: str | None = None) -> None:
	"""Raise unless ``percentage`` is within the user's ceiling (BR-031)."""
	permissions = get_pos_permission_set(user)
	limit = flt(permissions.get(ceiling_field))
	if flt(percentage) > limit:
		frappe.throw(
			_("Discount of {0}% exceeds your limit of {1}%.").format(flt(percentage), limit),
			frappe.PermissionError,
		)


def validate_branch_access(branch: str, user: str | None = None) -> None:
	"""Raise unless ``user`` may act in ``branch``.

	Branch scoping uses Frappe's own ``User Permission`` mechanism, so an
	administrator restricts a cashier to a branch the standard ERPNext way
	instead of through a parallel RPOS-only concept.
	"""
	user = user or frappe.session.user
	if is_superuser(user):
		return

	if not frappe.has_permission("Branch", doc=branch, user=user):
		frappe.throw(
			_("You do not have access to branch {0}.").format(branch),
			frappe.PermissionError,
		)


# --------------------------------------------------------------------------- #
# Privilege escalation guard (FR-12.6)
# --------------------------------------------------------------------------- #


def assert_may_edit_permission_set(role: str, new_values: dict, user: str | None = None) -> dict:
	"""Validate an edit to ``role``'s permission set and return the changed fields.

	    Enforces FR-12.6:

	1. never grant a permission you do not hold
	2. never raise a ceiling above your own
	3. never edit a role at or above your own rank
	4. (role assignment is guarded by :func:`assert_may_assign_role`)
	"""
	user = user or frappe.session.user
	booleans, ceilings = permission_fields()
	mine = get_pos_permission_set(user)

	if role not in ROLE_RANK:
		frappe.throw(_("{0} is not an RPOS role.").format(role))

	if ROLE_RANK[role] >= user_rank(user):
		frappe.throw(
			_("You cannot edit the permissions of {0}.").format(_(role)),
			frappe.PermissionError,
		)

	current = (
		frappe.db.get_value("POS Permission Set", role, booleans + ceilings, as_dict=True)
		if frappe.db.exists("POS Permission Set", role)
		else frappe._dict()
	)

	changes = {}
	for field, value in new_values.items():
		if field in SECRET_FIELDS:
			# The PIN is set through its own endpoint; it is never diffed or logged.
			continue

		if field not in booleans and field not in ceilings:
			continue

		before = current.get(field)

		if field in booleans:
			after = 1 if value else 0
			if after and not mine.get(field):
				frappe.throw(
					_("You cannot grant a permission you do not have: {0}.").format(field),
					frappe.PermissionError,
				)
			before = 1 if before else 0
		else:
			after = flt(value)
			if after > flt(mine.get(field)):
				frappe.throw(
					_("You cannot set {0} above your own limit of {1}%.").format(field, flt(mine.get(field))),
					frappe.PermissionError,
				)
			before = flt(before)

		if before != after:
			changes[field] = {"before": before, "after": after}

	return changes


def assert_may_assign_role(role: str, target_user: str, user: str | None = None) -> None:
	"""Raise unless ``user`` may grant or revoke ``role`` for ``target_user``."""
	user = user or frappe.session.user

	if role not in ROLE_RANK:
		frappe.throw(_("{0} is not an RPOS role.").format(role))

	if target_user == user and not is_superuser(user):
		frappe.throw(_("You cannot change your own roles."), frappe.PermissionError)

	if ROLE_RANK[role] >= user_rank(user):
		frappe.throw(_("You cannot assign the role {0}.").format(_(role)), frappe.PermissionError)


# --------------------------------------------------------------------------- #
# Manager override (08 §4, 07 §7)
# --------------------------------------------------------------------------- #


def find_approver_for_pin(action: str, pin: str) -> str | None:
	"""Return the role whose PIN matches and which grants ``action``.

	The PIN is compared through Frappe's hashed-password check; the stored value
	is never read. Returns ``None`` on any failure, with no detail about which
	part failed — a caller must not be able to probe for valid PINs.
	"""
	booleans, _ceilings = permission_fields()
	if action not in booleans:
		return None

	candidates = frappe.get_all("POS Permission Set", filters={action: 1}, pluck="name")

	for role in candidates:
		try:
			check_password(role, pin, doctype="POS Permission Set", fieldname="manager_pin")
		except frappe.AuthenticationError:
			continue
		except Exception:
			# No PIN configured for this role.
			continue
		return role

	return None


def issue_override_token(action: str, approved_by: str) -> str:
	"""Mint a single-use token authorising ``action`` for the next 60 seconds.

	Held server-side in the cache rather than signed into a JWT, so it can be
	consumed exactly once and revoked (DECISIONS.md D-015).
	"""
	token = frappe.generate_hash(length=48)
	frappe.cache().set_value(
		_OVERRIDE_CACHE_PREFIX + token,
		{"action": action, "approved_by": approved_by, "user": frappe.session.user},
		expires_in_sec=_OVERRIDE_TTL_SECONDS,
	)
	return token


def consume_override_token(token: str, action: str) -> str:
	"""Validate and burn ``token``, returning the approving role.

	Raises ``PermissionError`` if the token is missing, expired, already used,
	issued for a different action, or issued to a different user.
	"""
	if not token:
		frappe.throw(_("Manager authorisation is required."), frappe.PermissionError)

	key = _OVERRIDE_CACHE_PREFIX + token
	payload = frappe.cache().get_value(key)
	frappe.cache().delete_value(key)

	if not payload or payload.get("action") != action or payload.get("user") != frappe.session.user:
		frappe.throw(_("Manager authorisation is invalid or has expired."), frappe.PermissionError)

	return payload["approved_by"]

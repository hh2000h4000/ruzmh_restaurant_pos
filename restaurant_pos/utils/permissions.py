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

from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils import flt

# Rank decides who may edit whose permissions (FR-12.6 rule 3).
ROLE_RANK = {
	"POS Cashier": 10,
	"POS Senior Cashier": 20,
	"POS Manager": 30,
	"Restaurant Manager": 40,
	"Restaurant Admin": 50,
}

RPOS_ROLES = tuple(ROLE_RANK)

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

	Cached for the duration of the request.
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

	Branch scoping is a ``User Permission`` question, not a DocType-permission
	one: "which branches is this cashier restricted to", not "may this cashier
	open the Branch list in the desk".

	Reading it through ``frappe.has_permission("Branch")`` conflated the two and
	refused everyone, because no POS role has read access to ``Branch`` — a wall
	every cashier would have hit on every call. Here the rule is stated
	directly: no User Permission rows means unrestricted, which is the right
	default for a single-branch restaurant.
	"""
	allowed = allowed_branches(user)
	if allowed is None or branch in allowed:
		return

	frappe.throw(
		_("You do not have access to branch {0}.").format(branch),
		frappe.PermissionError,
	)


def allowed_branches(user: str | None = None) -> set[str] | None:
	"""The branches ``user`` is restricted to, or ``None`` for unrestricted.

	``None`` and an empty set mean opposite things, which is why this returns
	``None`` rather than "all branches": no ``User Permission`` rows means no
	restriction, and an empty set would lock every cashier out of everything.
	"""
	user = user or frappe.session.user
	if is_superuser(user):
		return None

	restricted_to = frappe.permissions.get_user_permissions(user).get("Branch") or []
	if not restricted_to:
		return None

	return {row.get("doc") for row in restricted_to}


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


# The PIN itself lives on the User, not on a role — see utils/manager_pin.py
# and DECISIONS.md D-016.


def guard_user_changes(doc, method=None) -> None:
	"""``User.validate`` — the four escalation rules, on the door people use (`D-201`).

	`assert_may_assign_role` had no caller outside its tests: the rules were
	written, proven, and reachable only through an API that nothing called. The
	desk form is where a role is actually granted, so the guard belongs on it.

	Superusers pass: a System Manager setting the restaurant up is the one who
	hands out the first roles, and locking them out locks out everyone.
	"""
	if is_superuser():
		return

	before = doc.get_doc_before_save()
	held = {row.role for row in (before.get("roles") or [])} if before else set()
	wanted = {row.role for row in (doc.get("roles") or [])}

	changes = {}
	for role in sorted((held ^ wanted) & set(ROLE_RANK)):
		assert_may_assign_role(role, doc.name)
		changes[role] = {"before": 1 if role in held else 0, "after": 1 if role in wanted else 0}

	# The PIN identifies a person and approves overrides, so setting somebody
	# else's is the same class of act as granting them a role.
	#
	# Read from `_new_manager_pin`, not the field: `hold_pin_aside` runs first in
	# this same hook and empties the column deliberately (`D-136`), so the field
	# is always blank by the time this sees it.
	if getattr(doc, "_new_manager_pin", None) and doc.name != frappe.session.user:
		assert_may_manage_pin_of(doc.name)

	doc._rpos_role_changes = changes


def log_user_changes(doc, method=None) -> None:
	"""``User.on_update`` — write the role change down once it has actually happened."""
	changes = getattr(doc, "_rpos_role_changes", None)
	if not changes:
		return

	from restaurant_pos.utils.audit import log_permission_change

	log_permission_change(target=doc.name, changes=changes, action_type="role_changed")
	doc._rpos_role_changes = {}


def assert_may_manage_pin_of(target_user: str, user: str | None = None) -> None:
	"""Raise unless ``user`` may set or clear ``target_user``'s PIN.

	Anyone may manage their own. Otherwise the actor must outrank the target,
	so a cashier cannot overwrite a manager's PIN and approve their own actions.
	"""
	user = user or frappe.session.user
	if target_user == user or is_superuser(user):
		return

	if user_rank(target_user) >= user_rank(user):
		frappe.throw(_("You cannot manage the PIN of {0}.").format(target_user), frappe.PermissionError)


def discount_override_action(ceiling_field: str, percentage: float) -> str:
	"""The token action for approving a specific discount.

	The percentage is part of the action, so a token approved for 10% cannot be
	presented for 90%. A plain ``discount_override`` action would let the client
	get a cheap approval and spend it on an expensive one.
	"""
	return f"{ceiling_field}:{flt(percentage, 2)}"


def find_approver_for_discount(ceiling_field: str, percentage: float, pin: str) -> str | None:
	"""The user whose PIN matches **and** whose own ceiling covers ``percentage``.

	Holding ``can_manual_promotion`` is not enough. A manager capped at 50%
	approving a 90% discount would make the cap meaningless — the point of a
	ceiling is that nobody can exceed their own.
	"""
	from restaurant_pos.utils.manager_pin import identify

	user = identify(pin)
	if not user or not frappe.db.get_value("User", user, "enabled"):
		return None

	permissions = get_pos_permission_set(user)
	if not permissions.get("can_manual_promotion"):
		return None

	return user if flt(percentage) <= flt(permissions.get(ceiling_field)) else None


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


# --------------------------------------------------------------------------- #
# Borrowed rights, for ERPNext's own documents
# --------------------------------------------------------------------------- #


@contextmanager
def server_rights():
	"""Borrow the framework's own rights for the length of one ERPNext call.

	**No POS role may read or write an accounting document** — deliberately.
	RPOS authorises through `POS Permission Set` and writes the sale itself with
	`ignore_permissions` (`08_Security.md` §1), so a cashier never needs desk
	rights on a `Sales Invoice`, and cannot list one either.

	Some of ERPNext's own code asks the **session** anyway, and takes no flag to
	say otherwise. Twice now that has meant a whole feature working perfectly for
	Administrator and dying on a bare `PermissionError` for every real user:

	* `make_return_doc` checks before it maps, so **no cashier could refund**
	  anything (`D-144`);
	* submitting a `POS Closing Entry` reaches `update_opening_entry`, which
	  saves the `POS Opening Entry` as whoever is standing there — so **no
	  cashier could hand their drawer back**, and no manager could end the day
	  (`D-157`).

	The alternative is to grant POS roles desk permissions on those doctypes,
	which hands every cashier every invoice the company has ever issued to
	satisfy one framework check. This is the smaller door: `frappe.session.user`
	and the two caches keyed on it, restored in `finally`, around a call whose
	authorisation **we have already done ourselves**. Documents inserted before
	the borrowing still carry the cashier's name, not this one.

	Wrap the narrowest call that needs it, never a whole endpoint.
	"""
	session = frappe.local.session
	caller = session.user

	def _reset(user: str) -> None:
		session.user = user
		# Both are keyed on the session user and would otherwise answer for the
		# wrong one on the way in *and* on the way out.
		frappe.local.role_permissions = {}
		frappe.local.user_perms = None

	_reset("Administrator")
	try:
		yield
	finally:
		_reset(caller)

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Per-user manager PIN used to approve overrides.

The PIN belongs to a **person**, not a role (`DECISIONS.md` D-016). A role-scoped
PIN is a secret shared by everyone holding the role, so
``POS Audit Log.approved_by`` could never name who actually approved — which is
the entire purpose of recording an override (08_Security.md §5).

Storage mirrors the correction in D-015: a ``Password`` DocField is persisted
reversibly (``encrypted = 1``) and is invisible to ``check_password()``, which
reads only ``encrypted = 0``. The value is therefore taken off the document
before save and written as a one-way hash.

Refs: 08_Security.md §4, FR-12.2, FR-12.8
"""

import frappe
from frappe import _
from frappe.utils.password import check_password, update_password

FIELDNAME = "pos_manager_pin"
PIN_LENGTH = 4


# --------------------------------------------------------------------------- #
# doc_events on User
# --------------------------------------------------------------------------- #


def hold_pin_aside(doc, method=None):
	"""``User.validate`` — keep the PIN out of reversible storage."""
	pin = (doc.get(FIELDNAME) or "").strip()
	doc.set(FIELDNAME, None)
	doc._new_manager_pin = None

	if not pin:
		return

	validate_format(pin)
	assert_pin_is_unique(pin, doc.name)
	doc._new_manager_pin = pin


def store_pin_hashed(doc, method=None):
	"""``User.on_update`` — write the one-way hash."""
	pin = getattr(doc, "_new_manager_pin", None)
	if not pin:
		return

	update_password(doc.name, pin, doctype="User", fieldname=FIELDNAME)
	doc._new_manager_pin = None


# --------------------------------------------------------------------------- #
# Operations
# --------------------------------------------------------------------------- #


def validate_format(pin: str) -> None:
	if not pin.isdigit() or len(pin) != PIN_LENGTH:
		frappe.throw(_("The manager PIN must be exactly {0} digits.").format(PIN_LENGTH))


def assert_pin_is_unique(pin: str, user: str | None = None) -> None:
	"""Reject a PIN already used by someone else.

	With only 10,000 possible values, collisions are likely in a chain. If two
	managers shared a PIN the audit trail would name whichever row was read
	first — an accountability failure worse than no PIN at all.
	"""
	owner = find_user_by_pin(pin)
	if owner and owner != user:
		frappe.throw(_("That PIN is already in use. Choose a different one."))


def set_pin(user: str, pin: str) -> None:
	"""Set or replace a user's PIN. Write-only; the value is never read back."""
	validate_format(pin)
	assert_pin_is_unique(pin, user)
	update_password(user, pin, doctype="User", fieldname=FIELDNAME)


def clear_pin(user: str) -> None:
	auth = frappe.qb.Table("__Auth")
	frappe.qb.from_(auth).delete().where(
		(auth.doctype == "User") & (auth.name == user) & (auth.fieldname == FIELDNAME)
	).run()


def has_pin(user: str) -> bool:
	"""Whether ``user`` has a PIN, without reading it (FR-12.8)."""
	return user in pin_holders()


def pin_holders() -> list[str]:
	"""Users with a PIN set. Read through the query builder because ``__Auth``
	is not a DocType, the same way Frappe's own password utilities read it."""
	auth = frappe.qb.Table("__Auth")
	rows = (
		frappe.qb.from_(auth)
		.select(auth.name)
		.where((auth.doctype == "User") & (auth.fieldname == FIELDNAME) & (auth.encrypted == 0))
		.run()
	)
	return [row[0] for row in rows]


def find_user_by_pin(pin: str) -> str | None:
	"""Return the user whose PIN matches, or ``None``."""
	for user in pin_holders():
		try:
			check_password(user, pin, doctype="User", fieldname=FIELDNAME)
		except Exception:
			continue
		return user

	return None


def find_approver_for_pin(action: str, pin: str) -> str | None:
	"""Return the user whose PIN matches **and** who holds ``action``.

	A valid PIN is not a master key. Returns ``None`` on any failure with no
	detail about which part failed, so a caller cannot probe for valid PINs.
	"""
	from restaurant_pos.restaurant_pos.utils.permissions import get_pos_permission_set

	user = find_user_by_pin(pin)
	if not user:
		return None

	if not frappe.db.get_value("User", user, "enabled"):
		return None

	return user if get_pos_permission_set(user).get(action) else None

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Announcements from the office to the tills (`D-303`).

The bell is one place for everything a cashier should know: the kitchen
tickets that did not print (`D-298`) and what the office has to say. An
announcement goes to people, not to terminals — a cashier reads it on
whichever till they sign in at — so, unlike a print alert, **reading it is
recorded on the server, per person**, and the sender sees who has.

Who receives it is decided once, when it is sent: everyone who works a till,
narrowed by branch and role, plus anybody named. Toast's pre-shift notes and
Square's announcements choose their audience the same way.

**And the office's own bell** — the user asked why ERPNext's notifications
were not used. Frappe has no screen to *write* a targeted message:
`Notification` is rules that fire on documents, and `Note` reaches every desk
user at login with no branch or role. So the writing stays here, but a
recipient who works in the desk also gets a Frappe `Notification Log` (type
Alert, which sends no email) and it rings in ERPNext's bell where they already
look. **The receipt stays on this record**: Frappe deletes its logs after 180
days, and the sender's "who read it" must outlive that.
"""

import frappe
from frappe import _
from frappe.query_builder import Order
from frappe.query_builder.functions import Count
from frappe.utils import getdate, now_datetime, nowdate

from restaurant_pos.utils.permissions import RPOS_ROLES, allowed_branches, user_rpos_roles

#: Roles that work only at the till — their bell is the till's, not ERPNext's.
TILL_ONLY_ROLES = {"POS Cashier", "POS Senior Cashier"}


def address(doc) -> None:
	"""Fix who receives it, and when and by whom it was sent."""
	people = recipients(doc)
	if not people:
		frappe.throw(_("Nobody would receive this announcement. Choose other branches, roles or people."))

	doc.sent_at = now_datetime()
	doc.sent_by = frappe.session.user
	doc.set("recipients", [{"user": user} for user in people])
	doc.read_count = _("{0} of {1}").format(0, len(people))


def recipients(doc) -> list[str]:
	"""Everyone who works a till, narrowed by branch and role, plus anybody named.

	**Named people only, when only people are named** — a note to two cashiers
	is not a note to the whole restaurant because nothing else was ticked.
	"""
	named = {row.user for row in doc.get("users") or []}
	branches = {row.branch for row in doc.get("branches") or []}
	roles = {row.role for row in doc.get("roles") or []}

	if named and not branches and not roles:
		return sorted(_enabled(named))

	holders = frappe.get_all(
		"Has Role",
		filters={"role": ("in", list(roles or RPOS_ROLES)), "parenttype": "User"},
		pluck="parent",
		distinct=True,
	)
	people = set(_enabled(holders))
	if branches:
		people = {user for user in people if _works_in(user, branches)}

	return sorted(people | _enabled(named))


def _enabled(users) -> set[str]:
	if not users:
		return set()
	return set(
		frappe.get_all(
			"User",
			filters={"name": ("in", list(users)), "enabled": 1, "user_type": "System User"},
			pluck="name",
		)
	)


def notify_office(doc) -> None:
	"""Ring ERPNext's own bell for every recipient who works in the desk.

	A cashier whose only RPOS roles are the till's is left out: their bell is
	the till's, and a second copy in a desk they never open is noise.
	"""
	office = [row.user for row in doc.recipients if _at_the_office(row.user)]
	if not office:
		return

	from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification

	enqueue_create_notification(
		office,
		{
			"type": "Alert",
			"document_type": doc.doctype,
			"document_name": doc.name,
			"from_user": doc.sent_by,
			"subject": (_("Urgent") + ": " if doc.urgent else "") + doc.subject,
			"email_content": doc.message,
		},
	)


def _at_the_office(user: str) -> bool:
	roles = set(user_rpos_roles(user))
	return not roles or not roles <= TILL_ONLY_ROLES


def _works_in(user: str, branches: set[str]) -> bool:
	"""A cashier restricted to no branch works in all of them (`validate_branch_access`)."""
	allowed = allowed_branches(user)
	return allowed is None or bool(allowed & branches)


def mine(user: str, limit: int) -> list[dict]:
	"""The newest announcements addressed to ``user``, still showing, newest first."""
	note, row = _tables()
	return [
		{
			"kind": "announcement",
			"key": found.name,
			"at": found.sent_at,
			"subject": found.subject,
			"message": found.message,
			"urgent": bool(found.urgent),
			"sender": frappe.get_cached_value("User", found.sent_by, "full_name") or found.sent_by,
			"read": bool(found.read_at),
		}
		for found in _showing(note, row, user)
		.select(note.name, note.subject, note.message, note.urgent, note.sent_at, note.sent_by, row.read_at)
		.orderby(note.sent_at, order=Order.desc)
		.orderby(note.name, order=Order.desc)
		.limit(limit)
		.run(as_dict=True)
	]


def unread(user: str) -> int:
	"""How many still showing that ``user`` has not read — their share of the badge."""
	note, row = _tables()
	return _showing(note, row, user).select(Count("*")).where(row.read_at.isnull()).run()[0][0]


def mark_read(user: str, name: str | None = None) -> int:
	"""Record that ``user`` read one announcement, or every one still showing.

	Only their own row is touched: a cashier marks what *they* read, and the
	sender's table says exactly who that was.
	"""
	note, row = _tables()
	query = _showing(note, row, user).select(row.name).where(row.read_at.isnull())
	if name:
		query = query.where(note.name == name)
	rows = query.run(pluck=True)

	now = now_datetime()
	parents = set()
	for child in rows:
		frappe.db.set_value("POS Announcement Recipient", child, "read_at", now, update_modified=False)
		parents.add(frappe.db.get_value("POS Announcement Recipient", child, "parent"))
	for parent in parents:
		_count_reads(parent)
		# Read at the till, so ERPNext's bell stops showing it unread too.
		frappe.db.set_value(
			"Notification Log",
			{"for_user": user, "document_type": "POS Announcement", "document_name": parent},
			"read",
			1,
			update_modified=False,
		)
	return len(rows)


def _count_reads(name: str) -> None:
	read = frappe.db.count("POS Announcement Recipient", {"parent": name, "read_at": ("is", "set")})
	total = frappe.db.count("POS Announcement Recipient", {"parent": name})
	frappe.db.set_value(
		"POS Announcement", name, "read_count", _("{0} of {1}").format(read, total), update_modified=False
	)


def _tables():
	return frappe.qb.DocType("POS Announcement"), frappe.qb.DocType("POS Announcement Recipient")


def _showing(note, row, user: str):
	"""Sent, not withdrawn, not past its day, and addressed to ``user``."""
	return (
		frappe.qb.from_(row)
		.join(note)
		.on(note.name == row.parent)
		.where(row.user == user)
		.where(row.parenttype == "POS Announcement")
		.where(note.docstatus == 1)
		.where(note.expires_on.isnull() | (note.expires_on >= getdate(nowdate())))
	)


# --------------------------------------------------------------------------- #
# Who may open one in the desk
# --------------------------------------------------------------------------- #


def may_send(user: str) -> bool:
	"""Whoever the role permissions let create one — "by the permissions", as the user put it."""
	from frappe.permissions import get_valid_perms

	return user == "Administrator" or any(
		perm.get("create") for perm in get_valid_perms("POS Announcement", user)
	)


def query_conditions(user: str | None = None) -> str | None:
	"""The list in the desk: a sender sees them all, anyone else what was sent to them."""
	user = user or frappe.session.user
	if may_send(user):
		return None
	return (
		"`tabPOS Announcement`.name in (select parent from `tabPOS Announcement Recipient`"
		f" where user = {frappe.db.escape(user)})"
	)


def has_permission(doc, ptype: str = "read", user: str | None = None) -> bool:
	"""Opened from ERPNext's bell: a recipient may read what was sent to them, and only that."""
	user = user or frappe.session.user
	if may_send(user):
		return True
	return ptype == "read" and any(row.user == user for row in doc.get("recipients") or [])

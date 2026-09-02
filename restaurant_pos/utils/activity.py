# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The story of one bill: every action on it, in order, with who did it.

**Why this is not `POS Audit Log`.** That one answers *"who did something that
needs accounting for"* — a void, an override, a refund. It is a compliance
record (`08_Security.md` §5): small, kept long, read by a manager looking for
one entry. This answers *"what happened to this bill"*, which is a different
question and roughly five hundred times the volume — a ten-item order writes a
dozen rows before it is paid. Folding them together would bury the one override
worth finding under a day of routine taps.

**Why not ERPNext's `Version`.** `Restaurant Order` already has
`track_changes`, and every save is recorded with the user and a field-level
diff. Nothing is lost today — but a diff is not a story: *"subtotal 32.00 →
64.00"* is how you infer that somebody added a second شيش طاووق, and there is no
diff at all for a cashier opening a bill, walking away and coming back. Those
are exactly the movements this is for, so it is written where the **intent** is
known rather than reconstructed from what the intent happened to change.

Refs: FR-12.7, 08_Security.md §5, D-106
"""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime

#: Actions that are only ever written from the screen, because the server never
#: sees them: a cashier opening a held bill, leaving it, and coming back.
VIEW_ACTIONS = ("viewed", "left")


def log(
	order,
	action: str,
	*,
	subject: str | None = None,
	details: dict | None = None,
	audit_log: str | None = None,
	user: str | None = None,
) -> str | None:
	"""Record one thing that happened to a bill. Returns the entry, or None.

	**Never raises.** A bill's history is worth having and is never worth losing
	the bill for: if this fails, the order it was describing must still save.
	The failure goes to the error log, where it is somebody's problem later
	rather than the cashier's problem now.

	`order` may be a document or a name, because half the callers hold one and
	half the other, and making each convert first is how a call site gets
	skipped.
	"""
	try:
		if isinstance(order, str):
			order = frappe.db.get_value(
				"Restaurant Order", order, ["name", "branch", "pos_profile"], as_dict=True
			)
			if not order:
				return None

		entry = frappe.get_doc(
			{
				"doctype": "POS Order Activity",
				"restaurant_order": order.name,
				"action": action,
				"subject": (subject or "")[:140] or None,
				"at": now_datetime(),
				"user": user or frappe.session.user,
				"branch": order.get("branch"),
				"pos_profile": order.get("pos_profile"),
				"audit_log": audit_log,
				"details": details or None,
			}
		)
		entry.insert(ignore_permissions=True)
		return entry.name
	except Exception:
		frappe.log_error(f"Could not record {action} on {order}", "RPOS activity")
		return None


def timeline(order_name: str) -> list[dict]:
	"""Everything that happened to one bill, oldest first.

	Oldest first because it is read as a story: what the cashier did, then what
	they did next. Every other list in this app is newest-first, and that is the
	right default for a list of *things*; this is a list of *events*.
	"""
	rows = frappe.get_all(
		"POS Order Activity",
		filters={"restaurant_order": order_name},
		fields=["name", "action", "subject", "at", "user", "audit_log", "details"],
		order_by="at asc, creation asc",
	)

	# A JSON field is stored as text and comes back as text. Parsed here, once,
	# rather than by each reader — a caller that forgot would index a string and
	# get a character.
	for row in rows:
		row.details = frappe.parse_json(row.details) if row.details else {}

	return rows


#: How long a bill's keystroke history is kept.
#:
#: Long enough to answer "what happened on that bill last month", short enough
#: that a busy branch is not carrying millions of rows it will never read. A
#: sensitive action is **not** subject to this: it lives in `POS Audit Log`,
#: which is a compliance record and is not pruned here.
KEEP_DAYS = 120


def prune_default() -> None:
	"""The scheduled clean-up (`hooks.py`)."""
	prune(KEEP_DAYS)


def prune(days: int) -> None:
	"""Drop activity older than `days` (`D-106`).

	A dozen rows per bill is a few million a year for a busy branch. The **order**
	is kept for ever; its keystroke-level history is not, and a year-old
	"quantity changed from 1 to 2" answers no question anybody still has.
	"""
	from frappe.utils import add_days, nowdate

	frappe.db.delete("POS Order Activity", {"at": ("<", add_days(nowdate(), -days))})

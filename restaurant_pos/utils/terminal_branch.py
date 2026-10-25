# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""A terminal's branch, read from one place (`D-391`, `D-393`).

`POS Profile.rpos_branch` is the terminal's own branch (stage 2, `D-392`), and
every place that needs a terminal's branch asks `branch_of` (stage 3). Ten
places used to walk terminal, hall, branch each in their own way.

**Transitional, until every site has migrated:** where the column is empty, or
not there yet on a site that has not run its migrate, the answer falls back to
the hall's branch, which is what the column is filled from. The code reaches a
site before its migrate does, and a till that loses its branch in between
cannot sell. The fallback goes in the cleanup stage.
"""

import frappe
from frappe import _

FIELD = "rpos_branch"


def _has_column() -> bool:
	return frappe.get_meta("POS Profile").has_field(FIELD)


def _hall_branch(section: str | None) -> str | None:
	return frappe.db.get_value("Restaurant Section", section, "branch") if section else None


def branch_of(pos_profile: str | None) -> str | None:
	"""The branch a terminal sells in, or None for a profile that is not a till."""
	if not pos_profile:
		return None
	fields = [FIELD, "restaurant_section"] if _has_column() else ["restaurant_section"]
	row = frappe.db.get_value("POS Profile", pos_profile, fields, as_dict=True)
	if not row:
		return None
	return row.get(FIELD) or _hall_branch(row.restaurant_section)


def required(pos_profile: str) -> str:
	"""The branch a terminal sells in — or the cashier is told it has none.

	One message for every endpoint that needs it. Five said the terminal had
	no "Restaurant Section", which a counter till never needs (`D-395`).
	"""
	branch = branch_of(pos_profile)
	if not branch:
		frappe.throw(
			_("The device {0} has no branch. Choose its branch on the device form.").format(pos_profile)
		)
	return branch


def branch_of_doc(doc) -> str | None:
	"""The same, for a terminal being saved: its own unsaved values."""
	return doc.get(FIELD) or _hall_branch(doc.get("restaurant_section"))


def is_till(pos_profile: str | None) -> bool:
	"""A POS Profile somebody made a till of. Any other stays ERPNext's (`D-309`)."""
	return bool(branch_of(pos_profile))


def terminals_in(branch: str) -> list[str]:
	"""The tills of one branch."""
	halls = frappe.get_all("Restaurant Section", filters={"branch": branch}, pluck="name")
	names = []
	if _has_column():
		names += frappe.get_all("POS Profile", filters={FIELD: branch}, pluck="name", order_by="creation")
		filters = {FIELD: ("is", "not set"), "restaurant_section": ("in", halls)}
	else:
		filters = {"restaurant_section": ("in", halls)}
	if halls:
		names += frappe.get_all("POS Profile", filters=filters, pluck="name", order_by="creation")
	return list(dict.fromkeys(names))


def all_terminals() -> list[str]:
	"""Every till on the site, oldest first."""
	names = frappe.get_all(
		"POS Profile", filters={"restaurant_section": ("is", "set")}, pluck="name", order_by="creation"
	)
	if _has_column():
		names += frappe.get_all(
			"POS Profile", filters={FIELD: ("is", "set")}, pluck="name", order_by="creation"
		)
	return list(dict.fromkeys(names))


def keep_with_hall(doc, method=None) -> None:
	"""`POS Profile.validate` — the branch follows the hall, and never disagrees with it.

	Empty, it takes the hall's branch. Set, it must be the hall's branch: a
	terminal in one branch with a hall of another would have two answers to
	"which branch", and every count, drawer and invoice number hangs off it.
	"""
	section = doc.get("restaurant_section")
	if section:
		_match_the_hall(doc, section)
	_stay_where_it_sold(doc)


def _stay_where_it_sold(doc) -> None:
	"""A terminal that has sold stays in its branch (`D-394`).

	Its invoices are numbered branch, device, count (`D-309`), and its days,
	drawers and stock were all that branch's. Moved, the next invoice would
	start another branch's sequence and the history would read as two tills.
	"""
	before = doc.get_doc_before_save()
	if not before:
		return
	was = branch_of_doc(before)
	if not was or branch_of_doc(doc) == was:
		return
	if frappe.db.exists("Restaurant Order", {"pos_profile": doc.name}):
		frappe.throw(
			_(
				"{0} has sold in {1}, and its invoices are numbered there. It cannot move to another branch."
			).format(doc.name, was)
		)


def _match_the_hall(doc, section: str) -> None:
	hall_branch = frappe.db.get_value("Restaurant Section", section, "branch")
	if not doc.get(FIELD):
		doc.set(FIELD, hall_branch)
	elif doc.get(FIELD) != hall_branch:
		frappe.throw(
			_(
				"The hall {0} belongs to {1}, and this device to {2}. Choose a hall of the device's branch."
			).format(section, hall_branch, doc.get(FIELD))
		)


def mismatches() -> list[dict]:
	"""Terminals whose branch column says something other than their hall."""
	rows = frappe.get_all(
		"POS Profile",
		filters={"restaurant_section": ("is", "set")},
		fields=["name", "restaurant_section", FIELD],
	)
	halls = dict(
		frappe.get_all(
			"Restaurant Section",
			filters={"name": ("in", [row.restaurant_section for row in rows] or [""])},
			fields=["name", "branch"],
			as_list=True,
		)
	)
	return [
		{"terminal": row.name, "hall_branch": halls.get(row.restaurant_section), "branch": row.get(FIELD)}
		for row in rows
		if row.get(FIELD) != halls.get(row.restaurant_section)
	]


def fill_from_halls() -> int:
	"""Give every terminal on a hall its hall's branch, then prove they agree.

	Only an empty column is written; one already set is left and checked. Any
	terminal whose column and hall disagree afterwards stops the migration,
	named — nothing is guessed. A terminal with no hall is not one of ours and
	is left without a branch, as it is left without a number (`D-309`).
	"""
	filled = 0
	for row in frappe.get_all(
		"POS Profile",
		filters={"restaurant_section": ("is", "set"), FIELD: ("is", "not set")},
		fields=["name", "restaurant_section"],
	):
		branch = frappe.db.get_value("Restaurant Section", row.restaurant_section, "branch")
		if branch:
			frappe.db.set_value("POS Profile", row.name, FIELD, branch, update_modified=False)
			filled += 1

	wrong = mismatches()
	if wrong:
		frappe.throw(
			"Terminal branch does not match its hall: "
			+ "; ".join(f"{w['terminal']} (hall: {w['hall_branch']}, column: {w['branch']})" for w in wrong)
		)
	return filled

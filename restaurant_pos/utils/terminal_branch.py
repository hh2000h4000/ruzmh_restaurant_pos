# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""A terminal's own branch, beside the hall it used to reach it through (`D-391`).

Stage 2 of separating a terminal from its hall. `POS Profile.rpos_branch` is
added and filled from the hall, and kept equal to it — nothing reads it yet.
The ten places that work a terminal's branch out still go through the hall;
moving them here is stage 3, once this column is proved to say the same.
"""

import frappe
from frappe import _

FIELD = "rpos_branch"


def keep_with_hall(doc, method=None) -> None:
	"""`POS Profile.validate` — the branch follows the hall, and never disagrees with it.

	Empty, it takes the hall's branch. Set, it must be the hall's branch: a
	terminal in one branch with a hall of another would have two answers to
	"which branch", and every count, drawer and invoice number hangs off it.
	"""
	section = doc.get("restaurant_section")
	if not section:
		return

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

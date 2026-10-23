# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Every printer belongs to one branch, and only that branch prints on it (`D-363`).

The load test sent a branch's kitchen tickets to another branch's kitchen
(`D-361`). That hole is closed in the routing; this closes the rest of the
ways one branch's paper can reach another's printer:

- **when a link is saved** — a station, a routing rule, a terminal or a
  printer's fallback that names a printer of another branch is refused, so the
  mistake never enters the data;
- **when a job is queued** — the last word: whatever chose the printer, a job
  for a document of one branch is not queued on another branch's printer.

One function asks the question for all of them (`CLAUDE.md` §5.5).
"""

import frappe
from frappe import _


def branch_of(printer: str | None) -> str | None:
	return frappe.get_cached_value("POS Printer", printer, "branch") if printer else None


def assert_in_branch(printer: str | None, branch: str | None, *, used_by: str) -> None:
	"""Refuse ``printer`` for something of ``branch``; ``used_by`` names that something."""
	if not printer or not branch:
		return

	owner = branch_of(printer)
	if owner != branch:
		frappe.throw(
			_("{0} is a printer of {1}; {2} belongs to {3} and cannot print on it.").format(
				frappe.get_cached_value("POS Printer", printer, "title") or printer, owner, used_by, branch
			),
			frappe.ValidationError,
		)


def check_terminal(doc, method=None) -> None:
	"""``POS Profile.validate`` — the terminal's own printer is one of its branch's."""
	from restaurant_pos.utils.terminal_branch import branch_of_doc

	assert_in_branch(doc.get("default_printer"), branch_of_doc(doc), used_by=doc.name)

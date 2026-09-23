# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Table state for a section.

``get_floor_plan`` is the endpoint the canvas floor plan will use in Phase 4
(``FR-5.1``). It is implemented now, with positions and status included, so the
order screen can pick a table from a list today and Phase 4 can draw the same
payload without an API change.

Refs: 07_API_Design.md §4, BR-060, BR-061, FR-5.1, FR-5.2
"""

import frappe
from frappe import _

from restaurant_pos.utils.order import FINAL_STATES, open_orders_on, set_table_status
from restaurant_pos.utils.permissions import validate_branch_access


@frappe.whitelist()
def get_floor_plan(section: str) -> dict:
	"""Every table in a section, with what is happening on it (07 §4)."""
	details = frappe.db.get_value(
		"Restaurant Section", section, ["name", "title", "title_ar", "branch"], as_dict=True
	)
	if not details:
		frappe.throw(_("Section {0} does not exist.").format(section))

	validate_branch_access(details.branch)

	plan = frappe.db.get_value(
		"Restaurant Floor Plan",
		{"section": section, "is_active": 1},
		["canvas_width", "canvas_height", "background_image"],
		as_dict=True,
	)

	tables = frappe.get_all(
		"Restaurant Table",
		filters={"section": section, "is_active": 1},
		fields=[
			"name",
			"table_number",
			"status",
			"capacity",
			"shape",
			"pos_x",
			"pos_y",
			"width",
			"height",
			"current_order",
		],
		order_by="table_number asc",
	)

	_annotate_orders(tables)

	# After the bills: a table with people at it stays occupied and carries the
	# booking as a note; only an empty one reads as reserved (`D-191`).
	from restaurant_pos.utils import reservation

	reservation.on_the_floor(tables, details.branch)

	return {
		"section": details,
		"floor_plan": plan or {"canvas_width": 1200, "canvas_height": 800},
		"tables": tables,
	}


def _annotate_orders(tables: list) -> None:
	"""Hang every open bill on its table, with when it opened and what is on it.

	Keyed by **table**, not by the table's `current_order`: a table may carry
	more than one bill where the branch allows it (`BR-066`), and a floor plan
	showing only the first would hide the other party's food and their money.

	Still two queries for the whole section rather than two per table: a busy
	section is fifty tables and the floor plan redraws on every realtime event
	(``04`` §8 gives it 300ms).
	"""
	names = [table.name for table in tables]
	if not names:
		return

	# **Both places a bill can hold a table** (`D-183`, `BR-063`). A party spread
	# across two tables keeps the first in `table` and the rest in `extra_tables`
	# (`tables_of`), and matching only the first left the joined table carrying
	# no bill at all: it drew "4 seats", exactly like an empty one, and tapping
	# it did nothing — `onTable` opens a bill when there is one and seats when
	# the table is free, and that was neither. A waiter tapping a table with
	# people at it got silence (`D-074`).
	joined_to = _joined_tables(names)

	bills = frappe.get_all(
		"Restaurant Order",
		filters={"status": ("not in", FINAL_STATES)},
		or_filters={"table": ("in", names), "name": ("in", list(joined_to) or [""])},
		fields=["name", "table", "daily_number", "opened_at", "status", "total_amount"],
		order_by="creation asc",
	)
	if not bills:
		for table in tables:
			table.orders = []
		return

	counts: dict[str, int] = {}
	for row in frappe.get_all(
		"Restaurant Order Item",
		filters={"parent": ("in", [bill.name for bill in bills]), "parenttype": "Restaurant Order"},
		fields=["parent", "status"],
	):
		if row.status != "void":
			counts[row.parent] = counts.get(row.parent, 0) + 1

	by_table: dict[str, list] = {}
	for bill in bills:
		row = {
			"name": bill.name,
			"daily_number": bill.daily_number,
			"status": bill.status,
			"total_amount": bill.total_amount,
			"item_count": counts.get(bill.name, 0),
			# When it was opened, not how long ago (`D-121`). "4,625 minutes"
			# is a true figure nobody can read; a bill from Tuesday says so.
			"opened_at": bill.opened_at,
		}

		# Its own table. A bill joined onto a table here may have started at one
		# in another section, and the key it lands under is simply never read —
		# `by_table` is only ever asked about this section's tables. A guard
		# here read well and did nothing, and a mutation run proved it.
		by_table.setdefault(bill.table, []).append(row)

		# And every table it was joined onto. The same bill hangs on each of
		# them, because each of them has the same party sitting at it.
		for table in joined_to.get(bill.name, ()):
			by_table.setdefault(table, []).append(row)

	for table in tables:
		table.orders = by_table.get(table.name, [])


def _joined_tables(names: list[str]) -> dict[str, list[str]]:
	"""Bills joined onto any of these tables, and which of them each holds.

	One query for the section rather than one per table: the floor plan redraws
	on every realtime event, and `_annotate_orders` is two queries by design.
	"""
	joined: dict[str, list[str]] = {}
	for row in frappe.get_all(
		"Restaurant Order Table",
		filters={"table": ("in", names), "parenttype": "Restaurant Order"},
		fields=["parent", "table"],
	):
		joined.setdefault(row.parent, []).append(row.table)

	return joined


@frappe.whitelist(methods=["POST"])
def update_status(table: str, status: str) -> dict:
	"""Change a table's status by hand — typically cleaning back to available.

	Refuses to free a table that still has an order on it; that is what closing
	or cancelling the order is for (BR-061).

	**POST only.** Frappe rolls back a GET's writes, so reached as a query this
	would answer "available" and change nothing (`D-226` learned it the hard way).
	"""
	allowed = {"available", "cleaning", "inactive"}
	if status not in allowed:
		frappe.throw(_("A table cannot be set to {0} by hand.").format(_(status)))

	section = frappe.db.get_value("Restaurant Table", table, "section")
	if not section:
		frappe.throw(_("Table {0} does not exist.").format(table))

	validate_branch_access(frappe.db.get_value("Restaurant Section", section, "branch"))

	# Asked of the orders rather than of the table's own `current_order`, which
	# names one bill and a table may now hold several (`BR-066`).
	open_bills = open_orders_on(table)
	if open_bills and status == "available":
		frappe.throw(_("Table {0} still has an open order.").format(table), frappe.ValidationError)

	set_table_status(table, status, open_bills[0] if open_bills and status != "available" else None)
	return {"table": table, "status": status}

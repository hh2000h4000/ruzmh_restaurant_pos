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
from frappe.utils import now_datetime, time_diff_in_seconds

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

	return {
		"section": details,
		"floor_plan": plan or {"canvas_width": 1200, "canvas_height": 800},
		"tables": tables,
	}


def _annotate_orders(tables: list) -> None:
	"""Add elapsed time and item count to occupied tables (FR-5.1).

	One query for every open order rather than one per table: a busy section is
	fifty tables, and the floor plan refreshes on every realtime event
	(``04`` §8 gives it 300ms).
	"""
	order_names = [row.current_order for row in tables if row.current_order]
	if not order_names:
		return

	orders = {
		row.name: row
		for row in frappe.get_all(
			"Restaurant Order",
			filters={"name": ("in", order_names)},
			fields=["name", "opened_at", "status", "total_amount"],
		)
	}

	counts: dict[str, int] = {}
	for row in frappe.get_all(
		"Restaurant Order Item",
		filters={"parent": ("in", order_names), "parenttype": "Restaurant Order"},
		fields=["parent", "status"],
	):
		if row.status != "void":
			counts[row.parent] = counts.get(row.parent, 0) + 1

	now = now_datetime()
	for table in tables:
		order = orders.get(table.current_order)
		if not order:
			continue

		table.order_status = order.status
		table.order_total = order.total_amount
		table.item_count = counts.get(order.name, 0)
		table.order_minutes = int(time_diff_in_seconds(now, order.opened_at) // 60) if order.opened_at else 0


@frappe.whitelist()
def update_status(table: str, status: str) -> dict:
	"""Change a table's status by hand — typically cleaning back to available.

	Refuses to free a table that still has an order on it; that is what closing
	or cancelling the order is for (BR-061).
	"""
	from restaurant_pos.utils.order import set_table_status

	allowed = {"available", "cleaning", "inactive"}
	if status not in allowed:
		frappe.throw(_("A table cannot be set to {0} by hand.").format(_(status)))

	current = frappe.db.get_value("Restaurant Table", table, ["section", "current_order"], as_dict=True)
	if not current:
		frappe.throw(_("Table {0} does not exist.").format(table))

	branch = frappe.db.get_value("Restaurant Section", current.section, "branch")
	validate_branch_access(branch)

	if current.current_order and status == "available":
		frappe.throw(_("Table {0} still has an open order.").format(table), frappe.ValidationError)

	set_table_status(table, status, current.current_order if status != "available" else None)
	return {"table": table, "status": status}

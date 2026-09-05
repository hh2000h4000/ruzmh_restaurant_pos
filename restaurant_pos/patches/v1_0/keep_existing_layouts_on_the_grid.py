# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Every layout that existed before `layout_mode` keeps its coordinates (D-141).

The new default is `flow`, because that is the mode a restaurant should reach
for. But a layout drawn by hand means what its `col_start` and `row_start` say,
and defaulting those to flow would silently rearrange a screen a shop had
already laid out — the kind of change nobody connects to an upgrade.

`update_modified=False`: this is a data shape, not an edit anybody made.
"""

import frappe


def execute() -> None:
	if not frappe.db.has_column("POS Screen Layout", "layout_mode"):
		return

	for layout in frappe.get_all("POS Screen Layout", pluck="name"):
		frappe.db.set_value("POS Screen Layout", layout, "layout_mode", "grid", update_modified=False)

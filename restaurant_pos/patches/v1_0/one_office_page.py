# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Fold the area pages back into the one office page (`D-348`).

For a day the office was eleven pages — a home page of tiles and one page per
area under it — and `Printing` and `POS Reports` had been pages of their own
for longer. They are cards on the home page now, opened by tapping a tile.

Deleting a workspace's JSON file does not delete the page from a site that has
it: it would stay in the sidebar, holding links the home page now also holds.
Only the pages this app made are removed, by name and by module.
"""

import frappe

FOLDED = (
	"POS Branches and Devices",
	"POS Menu",
	"POS Staff",
	"POS Floor",
	"POS Offers and Loyalty",
	"POS Daily Work",
	"POS Books and Logs",
	"POS Preferences",
	"POS Reports",
	"Printing",
)


def execute():
	for name in frappe.get_all(
		"Workspace",
		filters={"name": ("in", FOLDED), "module": "Restaurant POS", "parent_page": "Restaurant POS"},
		pluck="name",
	):
		frappe.delete_doc("Workspace", name, force=True, ignore_permissions=True)

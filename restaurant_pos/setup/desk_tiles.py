# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The block that draws the office pages as tiles (`D-347`).

A workspace can hold a `Custom HTML Block`, and that is how the tiles get onto
the page. **What is stored is one line** — a call into
`public/js/desk_tiles.bundle.js` — so the picture can change with the app's
code and the record in the database never has to.

Made here rather than shipped as a fixture, like every other default this app
needs (`D-013`), and on every migrate: a site that had the app before the tiles
has pages that name a block it does not have.
"""

import frappe

BLOCK = "RPOS Tiles"

CONTENT = {
	"html": '<div class="rpos-tiles"></div>',
	"script": "window.restaurant_pos && restaurant_pos.desk_tiles && restaurant_pos.desk_tiles(root_element);",
	"style": "",
	# Everybody who reaches the page: the server already drops the links a
	# reader may not open, so there is nothing here to hide.
	"private": 0,
}


def setup() -> None:
	if not frappe.db.exists("Custom HTML Block", BLOCK):
		frappe.get_doc({"doctype": "Custom HTML Block", "name": BLOCK} | CONTENT).insert(
			ignore_permissions=True
		)

	block = frappe.get_doc("Custom HTML Block", BLOCK)
	if (
		any((block.get(field) or "") != value for field, value in CONTENT.items() if field != "private")
		or block.private
	):
		block.update(CONTENT)
		block.save(ignore_permissions=True)
		# `validate` makes a block private for anybody who is not a workspace
		# manager, which is whoever happens to run the migrate.
		block.db_set("private", 0, update_modified=False)

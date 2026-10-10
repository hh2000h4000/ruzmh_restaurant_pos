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

#: Asked for when the page is drawn rather than loaded with the desk: a tab
#: that was open across an update has the old desk in it, and with the script
#: on the desk's own list that tab drew an empty page — which is how the owner
#: first saw the tiles (`D-347`).
SCRIPT = """
const mount = root_element.querySelector(".rpos-tiles");
const said = setTimeout(() => { mount.querySelector(".rpos-wait").hidden = false; }, 4000);
frappe.require("desk_tiles.bundle.js", () => {
	clearTimeout(said);
	restaurant_pos.desk_tiles(root_element);
});
""".strip()

CONTENT = {
	# **Never a blank page** (`CLAUDE.md` §5.5): if the tiles do not arrive, this
	# line shows after a moment and says what brings them. In both languages,
	# because a block's own HTML is not translated.
	"html": (
		'<div class="rpos-tiles"><p class="rpos-wait" hidden style="padding:24px 4px;color:var(--text-muted)">'
		"الصفحة ما اكتملت. حدّث المتصفح (Ctrl+Shift+R)، ولو ما تغيّر شي شغّل bench build ثم bench restart."
		"<br>This page did not finish loading. Reload (Ctrl+Shift+R); if nothing changes, run bench build and "
		"restart.</p></div>"
	),
	"script": SCRIPT,
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

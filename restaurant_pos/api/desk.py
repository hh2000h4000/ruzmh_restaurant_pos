# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""A desk page drawn as tiles — what it shows, and how each tile looks (`D-351`).

The tiles are Frappe's own shortcuts and cards, drawn as squares by
`public/js/desk_tiles.bundle.js` (`D-348`). This is the server's half:

- `tiles` — the page exactly as Frappe builds it for this reader, with each
  tile's chosen picture and colour laid on it. **One request**, in place of the
  one the page made before, so a look costs a page nothing to load.
- `style_tile` — choose a tile's look, from the page itself.
- `tile_page` — put the tiles block on a page, or take it off.

**The looks are kept here, not on the page.** Frappe rewrites a page's rows on
every save from its editor, and a picture kept on a row went with them — the
owner's gear disappeared from the Settings card that way.
"""

import json
import re

import frappe
from frappe import _
from frappe.desk.desktop import get_desktop_page
from frappe.utils import cint

from restaurant_pos.setup.desk_tiles import BLOCK

SETTINGS = "RPOS Tile Settings"

#: What a tile can be — and what its label is looked up among.
KINDS = ("Shortcut", "Card", "Link")

#: The blocks the tiles replace; the tiles are put just above the first of them.
WIDGETS = ("shortcut", "card")

_ICON = re.compile(r"^[a-z][a-z-]{0,29}$")
_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")


def may_style() -> bool:
	"""Whoever may edit a public page may dress it: Frappe's own rule, not a new one."""
	return "Workspace Manager" in frappe.get_roles()


def _only_stylers() -> None:
	if not may_style():
		frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)


@frappe.whitelist()
def tiles(page: str) -> dict:
	"""The page as Frappe draws it for this reader, with every tile's look on it."""
	drawn = get_desktop_page(page) or {}
	settings = frappe.get_cached_doc(SETTINGS)
	name = frappe.parse_json(page).get("name")

	# Frappe hands the labels over translated, and what was kept is the row's
	# own label — so a look answers to either.
	looks = {}
	for row in settings.looks:
		if row.page == name:
			look = {"icon": row.icon, "colour": row.colour}
			looks[(row.kind, row.label)] = look
			looks[(row.kind, _(row.label))] = look

	def dress(item, kind: str) -> None:
		look = looks.get((kind, item.get("label")))
		if look:
			item["look"] = look

	if looks:
		for shortcut in (drawn.get("shortcuts") or {}).get("items") or []:
			dress(shortcut, "Shortcut")
		for card in (drawn.get("cards") or {}).get("items") or []:
			dress(card, "Card")
			for link in card.get("links") or []:
				dress(link, "Link")

	drawn["look"] = {"colour": settings.tile_colour, "size": settings.tile_size}
	drawn["can_style"] = may_style()
	return drawn


@frappe.whitelist(methods=["POST"])
def style_tile(page: str, kind: str, label: str, icon: str | None = None, colour: str | None = None) -> dict:
	"""Give one tile a picture and a colour; with neither, back to its default."""
	_only_stylers()

	if kind not in KINDS:
		frappe.throw(_("Unknown kind of tile: {0}").format(kind))
	if icon and not _ICON.match(icon):
		frappe.throw(_("That picture is not one of the tiles' own."))
	if colour and not _COLOUR.match(colour):
		frappe.throw(_("A colour is written like #1F4D43."))

	label = _stored_label(page, kind, label)
	settings = frappe.get_doc(SETTINGS)
	row = next(
		(one for one in settings.looks if (one.page, one.kind, one.label) == (page, kind, label)), None
	)

	if not (icon or colour):
		if row:
			settings.remove(row)
	elif row:
		row.icon, row.colour = icon, colour
	else:
		settings.append("looks", {"page": page, "kind": kind, "label": label, "icon": icon, "colour": colour})

	# The guard above is the permission: the settings form has its own roles,
	# and a Workspace Manager need not be one of them.
	settings.save(ignore_permissions=True)
	return {"icon": icon, "colour": colour}


def _stored_label(page: str, kind: str, label: str) -> str:
	"""The row's own label for the one the page showed — which was translated."""
	if not frappe.db.exists("Workspace", page):
		return label

	doc = frappe.get_cached_doc("Workspace", page)
	if kind == "Shortcut":
		kept = [row.label or row.link_to for row in doc.shortcuts]
	else:
		kept = [row.label for row in doc.links if (row.type == "Card Break") == (kind == "Card")]

	return next((one for one in kept if one and label in (one, _(one))), label)


@frappe.whitelist(methods=["POST"])
def tile_page(page: str, on: int = 1) -> dict:
	"""Show a page as tiles, or as Frappe's own lists again.

	It adds or removes one block and touches nothing else on the page, which is
	what the editor does when the block is added by hand. The save is Frappe's
	own, with its own rule about who may change a public page.
	"""
	_only_stylers()

	doc = frappe.get_doc("Workspace", page)
	blocks = [block for block in json.loads(doc.content or "[]") if not _is_the_tiles(block)]
	doc.set("custom_blocks", [row for row in doc.custom_blocks if row.custom_block_name != BLOCK])

	if cint(on):
		# Above the widgets it redraws, and below whatever the page opens with —
		# a heading, an onboarding guide, a chart (`D-348`).
		at = next((i for i, block in enumerate(blocks) if block.get("type") in WIDGETS), len(blocks))
		blocks.insert(at, {"type": "custom_block", "data": {"custom_block_name": BLOCK, "col": 12}})
		doc.append("custom_blocks", {"custom_block_name": BLOCK, "label": BLOCK})

	doc.content = json.dumps(blocks, ensure_ascii=False)
	doc.save()
	return {"tiled": bool(cint(on))}


def _is_the_tiles(block: dict) -> bool:
	return block.get("type") == "custom_block" and (block.get("data") or {}).get("custom_block_name") == BLOCK


@frappe.whitelist()
def is_tiled(page: str) -> bool:
	"""Whether a page holds the tiles block — what the settings form's button reads."""
	content = frappe.db.get_value("Workspace", page, "content") or "[]"
	return any(_is_the_tiles(block) for block in json.loads(content))

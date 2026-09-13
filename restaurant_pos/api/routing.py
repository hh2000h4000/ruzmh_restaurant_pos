# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Which item groups a station prints — read and written in one place.

The model behind kitchen routing is `POS Printer Routing Rule`, and it is richer
than the everyday question: a rule can be scoped to an order type, a terminal or
a single item, and `BR-070` resolves seven levels of them. That richness is worth
keeping and is not what a manager does on a Tuesday. What they do is *"the grill
printer takes the grills, the cold station takes the salads"*.

So this is an **editor over the same rows**, not a second place to store them
(`CLAUDE.md` §5.5). Nothing new is stored; a tick becomes a routing rule and an
untick deletes one. The Printing workspace is the same idea — a friendlier way
into DocTypes that already existed.

**Scoped rules are never touched.** A rule that names an order type, a terminal
or a specific item was written deliberately by somebody solving a problem this
screen cannot see, and silently deleting it would be the worst kind of help.

Refs: BR-070, FR-7.1, D-017, D-095
"""

from __future__ import annotations

import frappe
from frappe import _

# **Guarded by the Production Center form's own permission** (`D-208`), not the
# till's role check: these serve that desk form, so whoever may read or write it
# may use them, and changing its permission in the desk moves them with it.

#: A rule this screen is allowed to own: an item group, going to a station, with
#: nothing else narrowing it.
SIMPLE = {"item": ("is", "not set"), "order_type": ("is", "not set"), "pos_profile": ("is", "not set")}


@frappe.whitelist()
def station_groups(production_center: str) -> dict:
	"""What this station prints today, and everything it could print."""
	center = frappe.get_doc("Production Center", production_center)
	frappe.has_permission("Production Center", "read", doc=center, throw=True)

	assigned = frappe.get_all(
		"POS Printer Routing Rule",
		filters=SIMPLE | {"production_center": production_center, "is_active": 1},
		pluck="item_group",
	)

	# Leaf groups only. A parent group would route its children too, which is a
	# real capability of `BR-070` and not something to offer by accident from a
	# list of tick boxes.
	available = frappe.get_all(
		"Item Group", filters={"is_group": 0}, fields=["name"], order_by="name asc", pluck="name"
	)

	return {
		"production_center": production_center,
		"title": center.title_ar or center.title,
		"branch": center.branch,
		"assigned": sorted(set(assigned)),
		"available": available,
		"elsewhere": _assigned_elsewhere(center.branch, production_center),
	}


@frappe.whitelist()
def set_station_groups(production_center: str, item_groups: list | str) -> dict:
	"""Make this station's simple routing exactly `item_groups`.

	A group assigned here is **taken off every other station** in the branch.
	Two stations claiming one group is not a richer configuration — it is a
	coin toss decided by rule age, and the cook who does not get the ticket has
	no way to find out why.
	"""
	center = frappe.get_doc("Production Center", production_center)
	frappe.has_permission("Production Center", "write", doc=center, throw=True)

	wanted = set(frappe.parse_json(item_groups) if isinstance(item_groups, str) else item_groups)

	mine = frappe.get_all(
		"POS Printer Routing Rule",
		filters=SIMPLE | {"production_center": production_center},
		fields=["name", "item_group"],
	)
	held = {row.item_group: row.name for row in mine}

	for group in held.keys() - wanted:
		frappe.delete_doc("POS Printer Routing Rule", held[group], ignore_permissions=True)

	for group in wanted - held.keys():
		_claim(center, group)

	frappe.db.commit()

	return station_groups(production_center)


def _claim(center, item_group: str) -> None:
	"""Route `item_group` here, taking it off whichever station had it."""
	for other in frappe.get_all(
		"POS Printer Routing Rule",
		filters=SIMPLE
		| {
			"branch": center.branch,
			"item_group": item_group,
			"production_center": ("!=", center.name),
		},
		pluck="name",
	):
		frappe.delete_doc("POS Printer Routing Rule", other, ignore_permissions=True)

	frappe.get_doc(
		{
			"doctype": "POS Printer Routing Rule",
			"branch": center.branch,
			"item_group": item_group,
			"production_center": center.name,
			"priority": 10,
			"is_active": 1,
		}
	).insert(ignore_permissions=True)


def _assigned_elsewhere(branch: str, production_center: str) -> dict:
	"""Group -> the other station that prints it, so the screen can say so."""
	rows = frappe.get_all(
		"POS Printer Routing Rule",
		filters=SIMPLE | {"branch": branch, "is_active": 1, "production_center": ("!=", production_center)},
		fields=["item_group", "production_center"],
	)

	titles = {}
	for row in rows:
		if row.production_center not in titles:
			center = frappe.db.get_value(
				"Production Center", row.production_center, ["title", "title_ar"], as_dict=True
			)
			titles[row.production_center] = (
				(center.title_ar or center.title) if center else row.production_center
			)

	return {row.item_group: titles[row.production_center] for row in rows if row.item_group}


# `D-209` — `unrouted_groups` stood here, called by nothing but its own test.
# The gap it named is real (`BR-070` level 7 sends an unrouted group to the
# cashier's printer, and the cook never sees it); a screen that shows it is
# welcome, and the query is in the history.

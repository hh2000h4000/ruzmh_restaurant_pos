# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Kitchen routing — which Production Center prepares each item.

Implements the seven-level ladder of ``BR-070``:

===== ==================================================
Level Source
===== ==================================================
1     Routing rule: Order Type x Item
2     Routing rule: Order Type x Item Group
3     Routing rule: POS Profile x Item
4     Routing rule: POS Profile x Item Group
5     ``Item.default_production_center``
6     ``Item Group.default_production_center``
7     Fallback: the cashier's printer on the POS Profile
===== ==================================================

``BR-070`` orders by specificity while ``FR-6.2`` says rules are evaluated in
``priority`` order, first match wins. The two only agree if specificity comes
first: ``priority`` breaks ties *within* a level (``DECISIONS.md`` D-017).

Everything is resolved in one pass over pre-loaded data. Resolving per item with
its own queries is the N+1 pattern `04_performance_security.md` names explicitly,
and an order with twenty lines would issue hundreds of queries.

Refs: BR-070, BR-071, BR-072, FR-6.2, FR-6.3
"""

import frappe
from frappe import _
from frappe.utils import cint

FALLBACK_LEVEL = 7

# Specificity of a rule's context and item scope. Higher wins. A blank field is
# a wildcard (`05_Database_Design.md` §11: "Blank = all order types"), so it
# still matches — it just ranks below an explicit value.
_CONTEXT_RANK = {"order_type": 2, "pos_profile": 1, "any": 0}
_ITEM_RANK = {"item": 2, "item_group": 1}

# Where a matched rule sits on the BR-070 ladder, keyed by (context, item scope).
# Wildcard-context rules fall in beside the POS-profile tier: they are less
# specific than an order-type rule and no more specific than a profile one.
_LEVEL = {
	(2, 2): 1,
	(2, 1): 2,
	(1, 2): 3,
	(1, 1): 4,
	(0, 2): 3,
	(0, 1): 4,
}


class Route(frappe._dict):
	"""Where one item goes, and why.

	``level`` and ``matched_rule`` exist so the decision can be asserted in tests
	and explained in production when a manager asks why a burger printed at the
	bar.
	"""

	@property
	def is_fallback(self) -> bool:
		return self.level == FALLBACK_LEVEL


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def resolve_routes(
	item_codes: list[str],
	*,
	branch: str,
	order_type: str | None = None,
	pos_profile: str | None = None,
) -> dict[str, Route]:
	"""Resolve the production center for every item in one pass."""
	item_codes = list(dict.fromkeys(item_codes))
	if not item_codes:
		return {}

	items = _load_items(item_codes)
	groups = _load_item_groups()
	rules = _load_rules(branch)
	elsewhere = _centers_of_other_branches(branch)
	fallback_printer = (
		frappe.db.get_value("POS Profile", pos_profile, "default_printer") if pos_profile else None
	)

	return {
		code: _resolve_one(
			code,
			items.get(code) or frappe._dict(),
			groups,
			rules,
			order_type=order_type,
			pos_profile=pos_profile,
			fallback_printer=fallback_printer,
			elsewhere=elsewhere,
		)
		for code in item_codes
	}


def resolve_route(
	item_code: str,
	*,
	branch: str,
	order_type: str | None = None,
	pos_profile: str | None = None,
) -> Route:
	"""Single-item convenience wrapper. Prefer :func:`resolve_routes` in a loop."""
	return resolve_routes([item_code], branch=branch, order_type=order_type, pos_profile=pos_profile)[
		item_code
	]


def group_by_production_center(routes: dict[str, Route]) -> dict[str | None, list[str]]:
	"""Group item codes by production center, for KOT generation (FR-6.3).

	Items that fell through to the cashier printer are grouped under ``None``.
	"""
	grouped: dict[str | None, list[str]] = {}
	for code, route in routes.items():
		grouped.setdefault(route.production_center, []).append(code)

	return grouped


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def _load_items(item_codes: list[str]) -> dict[str, frappe._dict]:
	rows = frappe.get_all(
		"Item",
		filters={"name": ("in", item_codes)},
		fields=["name", "item_group", "default_production_center"],
	)
	return {row.name: row for row in rows}


def _centers_of_other_branches(branch: str) -> set[str]:
	"""Stations that belong to some other branch (`D-361`).

	A rule is read for the order's branch, but an item's or a group's default
	station is one value for the whole company — and it named the first
	branch's kitchen. The load test sold burgers in a branch with no printer at
	all, and 330 of its tickets went to the other branch's kitchen printer. A
	station with no branch is shared and stays usable everywhere.
	"""
	return set(
		frappe.get_all("Production Center", filters={"branch": ("not in", ["", None, branch])}, pluck="name")
	)


def _load_item_groups() -> dict[str, frappe._dict]:
	"""Every Item Group with its parent and default centre.

	Loaded whole because the tree is walked upwards per item; the table is a
	handful of rows in any real menu.
	"""
	rows = frappe.get_all(
		"Item Group",
		fields=["name", "parent_item_group", "default_production_center"],
	)
	return {row.name: row for row in rows}


def _load_rules(branch: str) -> list[frappe._dict]:
	"""Active rules for the branch, already in resolution order."""
	rules = frappe.get_all(
		"POS Printer Routing Rule",
		filters={"branch": branch, "is_active": 1},
		fields=[
			"name",
			"order_type",
			"pos_profile",
			"item",
			"item_group",
			"production_center",
			"priority",
			"creation",
		],
	)

	for rule in rules:
		rule.context_rank = _CONTEXT_RANK[
			"order_type" if rule.order_type else "pos_profile" if rule.pos_profile else "any"
		]
		rule.item_rank = _ITEM_RANK.get("item" if rule.item else "item_group" if rule.item_group else None)

	# A rule with neither item nor item_group targets nothing specific; 05 §11
	# treats item and item_group as the rule's subject, so it is not routable.
	rules = [rule for rule in rules if rule.item_rank]

	# Specificity first (BR-070), then priority, then age for determinism.
	rules.sort(key=lambda r: (-r.context_rank, -r.item_rank, cint(r.priority), r.creation))
	return rules


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #


def _resolve_one(
	item_code: str,
	item: frappe._dict,
	groups: dict[str, frappe._dict],
	rules: list[frappe._dict],
	*,
	order_type: str | None,
	pos_profile: str | None,
	fallback_printer: str | None,
	elsewhere: frozenset[str] | set[str] = frozenset(),
) -> Route:
	ancestry = _ancestry(item.get("item_group"), groups)

	# Levels 1-4 — configured rules, most specific first.
	for rule in rules:
		if rule.order_type and rule.order_type != order_type:
			continue
		if rule.pos_profile and rule.pos_profile != pos_profile:
			continue

		if rule.item:
			if rule.item != item_code:
				continue
		elif rule.item_group not in ancestry:
			continue

		return Route(
			item=item_code,
			production_center=rule.production_center,
			level=_LEVEL[(rule.context_rank, rule.item_rank)],
			matched_rule=rule.name,
			printer=None,
		)

	# Level 5 — the item's own default, when it is a station of this branch.
	if item.get("default_production_center") and item.default_production_center not in elsewhere:
		return Route(
			item=item_code,
			production_center=item.default_production_center,
			level=5,
			matched_rule=None,
			printer=None,
		)

	# Level 6 — the nearest ancestor group that declares a default.
	for group in ancestry:
		default = groups[group].get("default_production_center")
		if default and default not in elsewhere:
			return Route(
				item=item_code,
				production_center=default,
				level=6,
				matched_rule=None,
				printer=None,
				item_group=group,
			)

	# Level 7 — nothing matched; the cashier's printer takes it.
	return Route(
		item=item_code,
		production_center=None,
		level=FALLBACK_LEVEL,
		matched_rule=None,
		printer=fallback_printer,
	)


def _ancestry(item_group: str | None, groups: dict[str, frappe._dict]) -> list[str]:
	"""The item's group then each ancestor, nearest first.

	Item Group is a tree, so a rule or default set on a parent applies to
	everything beneath it — otherwise a manager would have to repeat the same
	rule for every leaf group on the menu.
	"""
	chain: list[str] = []
	current = item_group

	while current and current in groups and current not in chain:
		chain.append(current)
		current = groups[current].get("parent_item_group")

	return chain


# --------------------------------------------------------------------------- #
# Printer selection (BR-071, BR-072)
# --------------------------------------------------------------------------- #


def printer_for(production_center: str) -> frappe._dict:
	"""The primary and fallback printer of a production center.

	The caller tries ``printer`` first and falls back on failure (BR-072); the
	5-second timeout and the actual send belong to the Phase 3 print service.
	"""
	center = frappe.db.get_value(
		"Production Center",
		production_center,
		["printer", "fallback_printer", "has_kds", "auto_print_on_send", "is_active"],
		as_dict=True,
	)

	if not center:
		frappe.throw(_("Production Center {0} does not exist.").format(production_center))

	return center

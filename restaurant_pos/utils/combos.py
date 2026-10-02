# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""A combo: one tile on the menu, and the items it is made of are what is sold (`D-285`).

**The shape every till in the trade uses.** Square's combo is options with a
required number of selections, each item routed to its own station and counted
in item sales; Lightspeed's is choice groups priced from the cheapest option up;
Odoo 17 splits the combo's price over its lines by the ratio of their own
prices; Fitec (the owner's reference) shows the combo as a header with its items
under it, priced from the head or from the items. ZATCA's promotions guideline
treats such a bundle as *multiple supplies* — each item its own value, shown on
the tax invoice — and IFRS 15 ¶76 allocates a single price by relative
standalone selling price.

**Built on the add-on path, not beside it** (`D-284`, `CLAUDE.md` §5.5). A
combo's choices ship to the till as modifier groups, so the till's own popup asks
them — "pick one of these" is the question it already asks — and the offline
arithmetic prices them unchanged. On the order the combo is **one line** with
its items in `modifiers`, so a quantity change, a void, a split and a return
move the whole meal as one. The line is taken apart only where the parts matter:
the kitchen (each item to its station) and the invoice (each item sold).

- **fixed** — the combo's own price; a choice marked «adds to price» adds its
  price on top. On the invoice the price is shared over the items by their own
  prices.
- **sum** — the items' prices added up, each from its price list or typed on
  the row.

Refs: FR-4.2, D-284, D-285
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from restaurant_pos.utils import addons

#: A combo's choices travel as modifier groups named ``combo:<combo>:<choice>``,
#: which no real group can be called (a group is named by its title).
PREFIX = "combo:"

#: A combo item's own modifier groups travel as ``combo-part:<combo>|<item>|<group>``,
#: shown only while that item is the one chosen (`D-289`).
PART_PREFIX = "combo-part:"

#: The effect a combo's item carries on the order line — neither an add-on sold
#: under a dish nor one left out of its recipe, but the thing being sold.
EFFECT = "combo"


def is_combo(item: str) -> bool:
	return bool(frappe.db.get_value("Item", item, "rpos_is_combo"))


def definition(item: str) -> frappe._dict | None:
	if not is_combo(item):
		return None
	rows = frappe.get_all(
		"POS Combo Item",
		filters={"parent": item, "parenttype": "Item"},
		fields=["slot", "item", "qty", "price_source", "price", "is_default", "adds_to_price"],
		order_by="idx",
	)
	return frappe._dict(
		pricing=frappe.db.get_value("Item", item, "rpos_combo_pricing") or "fixed",
		rows=_with_groups(item, rows),
	)


def _with_groups(combo: str, rows: list) -> list:
	"""A row with a choice and no item offers the choice's whole item group (`D-294`).

	Square's combo option holds items or categories; Fitec's choice names the
	groups its components come from; Foodics picks the group first. So «any
	drink» is one row, and a drink added to the menu tomorrow is in the combo
	without anybody touching it — and one disabled leaves it.

	**Inside the combo's price**: a group's items come at their own list price
	as the share's weight and nothing on top. A row naming one of them under the
	same choice prices it differently («fresh juice +3») and wins.
	"""
	named = {(row.slot, row.item) for row in rows if row.item}
	expanded = []
	for row in rows:
		if row.item:
			expanded.append(row)
			continue
		group = choice(row.slot).item_group if row.slot else None
		for code in _sales_items_in(group, exclude=combo):
			if (row.slot, code) in named:
				continue
			named.add((row.slot, code))
			expanded.append(
				frappe._dict(
					slot=row.slot,
					item=code,
					qty=1,
					price_source="item_price",
					price=0,
					is_default=0,
					adds_to_price=0,
				)
			)
	return expanded


def _sales_items_in(group: str | None, exclude: str) -> list[str]:
	"""Every enabled sales item in a group or under it — not a combo."""
	if not group:
		return []
	bounds = frappe.db.get_value("Item Group", group, ["lft", "rgt"], as_dict=True)
	if not bounds:
		return []
	groups = frappe.get_all(
		"Item Group", filters={"lft": (">=", bounds.lft), "rgt": ("<=", bounds.rgt)}, pluck="name"
	)
	return frappe.get_all(
		"Item",
		filters={
			"item_group": ("in", groups),
			"is_sales_item": 1,
			"disabled": 0,
			"rpos_is_combo": 0,
			"name": ("!=", exclude),
		},
		pluck="name",
		order_by="item_name asc",
	)


def choice(slot: str) -> frappe._dict:
	"""A choice's names and how many to pick — one, when nobody set it up otherwise (`D-290`)."""
	found = frappe.db.get_value(
		"POS Combo Choice",
		slot,
		["title", "title_ar", "min_selections", "max_selections", "item_group"],
		as_dict=True,
	)
	return found or frappe._dict(
		title=slot, title_ar=slot, min_selections=1, max_selections=1, item_group=None
	)


def group_name(combo: str, slot: str) -> str:
	return f"{PREFIX}{combo}:{slot}"


def _list_price(item: str, price_list: str | None) -> float | None:
	"""An item's price for one unit of stock — one rule with the add-ons'."""
	return addons.list_price(item, price_list)


def row_price(row, price_list: str | None) -> float:
	"""What one row of the combo is worth, all of its quantity together."""
	if row.price_source == "amount":
		return flt(row.price, 2)
	return flt(flt(_list_price(row.item, price_list)) * (flt(row.qty) or 1), 2)


def _counts_in_price(row, pricing: str) -> bool:
	return pricing == "sum" or bool(row.slot and row.adds_to_price)


def base_price(combo: str, price_list: str | None) -> float | None:
	"""The price before any choice: the combo's own, or its fixed items added up."""
	spec = definition(combo)
	if not spec:
		return None
	if spec.pricing == "fixed":
		return _list_price(combo, price_list)
	return flt(sum(row_price(row, price_list) for row in spec.rows if not row.slot), 2)


def groups_for(combo: str, price_list: str | None) -> list[dict]:
	"""The combo's choices as the till's modifier groups — one required pick each."""
	spec = definition(combo)
	if not spec:
		return []

	groups: dict[str, dict] = {}
	for row in spec.rows:
		if not row.slot:
			continue
		if row.slot not in groups:
			rule = choice(row.slot)
			groups[row.slot] = {
				"name": group_name(combo, row.slot),
				"title": rule.title,
				"title_ar": rule.title_ar,
				# `D-290` — Square's number of selections, Toast's minimum and maximum.
				"selection_type": "single" if rule.max_selections == 1 else "multiple",
				"is_required": 1 if rule.min_selections else 0,
				"min_selections": rule.min_selections,
				"max_selections": rule.max_selections,
				"options": [],
			}
		group = groups[row.slot]
		price = row_price(row, price_list) if _counts_in_price(row, spec.pricing) else 0.0
		group["options"].append(
			frappe._dict(
				# The item's code is what comes back; the names are what is read.
				title=row.item,
				title_ar=_display_name(row.item),
				label=frappe.db.get_value("Item", row.item, "item_name"),
				price_effect="add" if price else "none",
				price_amount=price,
				is_default=row.is_default,
			)
		)
	return list(groups.values())


def slot_names(combo: str) -> list[str]:
	"""The groups the till opens for this combo: its choices, then its items' own groups."""
	spec = definition(combo)
	seen: list[str] = []
	for row in spec.rows if spec else []:
		if row.slot and row.slot not in seen:
			seen.append(row.slot)
	return [group_name(combo, slot) for slot in seen] + [part["name"] for part in part_groups(combo)]


def part_group_name(combo: str, item: str, group: str) -> str:
	return f"{PART_PREFIX}{combo}|{item}|{group}"


def part_groups(combo: str) -> list[dict]:
	"""Each combo item's own modifier groups — extra cheese on the meal's burger (`D-289`).

	**The item's groups, not a second set** (`CLAUDE.md` §5.5): the burger in the
	meal asks what the burger asks on its own. A group of an item under a choice
	is shown only while that item is chosen — ``when`` names the choice and the
	item — and a fixed item's groups always.
	"""
	spec = definition(combo)
	found = []
	for row in spec.rows if spec else []:
		for assigned in frappe.get_all(
			"Modifier Group Assignment",
			filters={"parent": row.item, "parenttype": "Item"},
			fields=["modifier_group"],
			order_by="idx",
		):
			name = part_group_name(combo, row.item, assigned.modifier_group)
			if any(part["name"] == name for part in found):
				continue
			found.append(
				{
					"name": name,
					"group": assigned.modifier_group,
					"item": row.item,
					"item_name": _display_name(row.item),
					"when": {"group": group_name(combo, row.slot), "option": row.item} if row.slot else None,
				}
			)
	return found


def resolve(combo: str, selected: list | None, price_list: str | None) -> tuple[list, float]:
	"""The items a combo line sells, from the choices the till sent (FR-4.2).

	**As many items per choice as the choice allows, from that choice's rows**
	(`D-290`), and every fixed item with it. Prices are read here, never taken from the client (`D-020`). Each entry
	keeps the item's own price as ``weight`` — what the invoice shares the
	combo's price by.
	"""
	spec = definition(combo)
	picked: dict[str, list[str]] = {}
	extras: dict[str, list] = {}
	for sent in selected or []:
		group = sent.get("group") or ""
		if group.startswith(part_group_name(combo, "", "")[:-1]):
			item, _sep, real = group[len(part_group_name(combo, "", "")[:-1]) :].partition("|")
			extras.setdefault(item, []).append({"group": real, "option": sent.get("option")})
			continue
		if not group.startswith(group_name(combo, "")):
			frappe.throw(_("{0} is not one of this combo's choices.").format(group))
		slot = group[len(group_name(combo, "")) :]
		picked.setdefault(slot, []).append(sent.get("option"))

	for slot in sorted({row.slot for row in spec.rows if row.slot} | set(picked)):
		rule = choice(slot)
		count = len(picked.get(slot, []))
		if count < cint(rule.min_selections) or (rule.max_selections and count > cint(rule.max_selections)):
			frappe.throw(
				_("Choose between {0} and {1} for {2}.").format(
					rule.min_selections, rule.max_selections or _("any number"), rule.title_ar
				)
			)

	resolved, delta = [], 0.0
	for row in spec.rows:
		if row.slot and row.item not in picked.get(row.slot, []):
			continue
		price = row_price(row, price_list)
		counted = row.slot and _counts_in_price(row, spec.pricing)
		if counted:
			delta += price
		resolved.append(
			{
				"group": row.slot or "",
				"option": frappe.db.get_value("Item", row.item, "item_name"),
				"option_ar": _display_name(row.item),
				"price_effect": "add" if counted and price else "none",
				"amount": price if counted else 0.0,
				"item": row.item,
				"item_effect": EFFECT,
				"item_qty": flt(row.qty) or 1,
				"weight": flt(flt(_list_price(row.item, price_list)) * (flt(row.qty) or 1), 2) or price,
			}
		)

	unknown = [
		(slot, item)
		for slot, items in picked.items()
		for item in items
		if not any(e["item"] == item and e["group"] == slot for e in resolved)
	]
	if unknown:
		frappe.throw(_("{0} is not offered under {1}.").format(unknown[0][1], unknown[0][0]))

	delta += _resolve_extras(resolved, extras, price_list)
	return resolved, delta


def _resolve_extras(parts: list[dict], extras: dict[str, list], price_list: str | None) -> float:
	"""Price each combo item's own add-ons the way the item alone would be (`D-289`).

	The item's modifier rules, read by the same function a dish's are — so the
	burger in the meal takes extra cheese at the price, and with the stock, it
	takes on its own. Per piece of the item, as an add-on is per dish.
	"""
	from restaurant_pos.utils.order import _resolve_modifiers

	delta = 0.0
	for item, chosen in extras.items():
		part = next((p for p in parts if p["item"] == item), None)
		if part is None:
			frappe.throw(_("{0} is not in this combo as ordered.").format(item))
		resolved, part_delta = _resolve_modifiers(item, chosen, price_list)
		part["modifiers"] = resolved
		delta += part_delta * (flt(part.get("item_qty")) or 1)
	return delta


def spec_pricing(combo: str) -> str:
	return frappe.db.get_value("Item", combo, "rpos_combo_pricing") or "fixed"


def parts(row) -> list[dict]:
	"""The items one combo line sold, as stored on it."""
	return [c for c in addons.chosen(row.modifiers) if c.get("item_effect") == EFFECT]


def invoice_lines(row) -> list[dict]:
	"""The combo's items as invoice lines, sharing the line's money (`D-285`).

	**By each item's own price** — Odoo's rule and IFRS 15 ¶76 — so a 29.00 meal
	of a 20.00 burger, 8.00 fries and 7.00 drink bills them 16.57, 6.63 and
	5.80. Each share is rounded to the halala and the last item takes what the
	rounding left, so the lines add up to exactly what the till showed. An item
	whose price nobody knows shares by nothing; when none is known, equally.

	No line for the combo itself: it is not a supply, its items are (ZATCA's
	*multiple supplies*). Each line is one portion of the item, so a combo with
	six nuggets sells one portion that takes six from stock — the add-on path.
	"""
	items = parts(row)
	qty = flt(row.qty)
	unit = flt(row.amount) / qty if qty else 0.0
	# `D-289` — an item's add-ons stay with the item, as under a dish: one sold
	# as stock is its own line at its price, and one that only changes the price
	# («large», «double cheese» with no stock behind it) goes on its item's line.
	# What the items share is the combo's price, and nothing chosen on one of them.
	own = []
	for choice in items:
		pieces = flt(choice.get("item_qty")) or 1
		# The choice's own price — an upgrade on a fixed meal, or the item's price
		# in a meal priced by its items — is the chosen item's money too.
		surcharge = flt(choice.get("amount")) if choice.get("price_effect") == "add" else 0.0
		for extra in choice.get("modifiers") or []:
			money = {"add": 1, "subtract": -1}.get(extra.get("price_effect"), 0) * flt(extra.get("amount"))
			if extra.get("item") and extra.get("item_effect") == "sell":
				unit -= money * pieces
			else:
				surcharge += money * pieces
		own.append(surcharge)
	unit -= sum(own)
	# **Who shares what is left.** A fixed meal's price is every item's. A meal
	# priced by its items has its fixed items' prices left, which are theirs;
	# with none, whatever remains (a manager's price change) is everyone's.
	sharing = [
		not (spec_pricing(row.item) == "sum" and any(not c.get("group") for c in items) and c.get("group"))
		for c in items
	]
	weights = [flt(c.get("weight")) if shares else 0.0 for c, shares in zip(items, sharing, strict=True)]
	total = sum(weights)
	if not total:
		weights = [1.0 if shares else 0.0 for shares in sharing]
		total = sum(weights)
	last = max(index for index, shares in enumerate(sharing) if shares)

	lines, given = [], 0.0
	for index, (choice, weight) in enumerate(zip(items, weights, strict=True)):
		if index == last:
			share = flt(unit - given, 2)
		else:
			share = flt(unit * weight / total, 2) if total else 0.0
		given += share
		share = flt(share + own[index], 2)
		line = {
			"item_code": choice["item"],
			"qty": qty,
			"rate": share,
			"rpos_order_item": row.name,
			"rpos_combo": row.item,
		}
		if not share:
			line.update({"price_list_rate": 0, "is_free_item": 1})
		portion = flt(choice.get("item_qty")) or 1
		if portion != 1:
			line.update({"uom": addons.PORTION, "conversion_factor": portion})
		removed = addons.removed_items(choice.get("modifiers"))
		if removed:
			line["rpos_removed"] = frappe.as_json(removed)
		lines.append(line)
		for extra in addons.sold_lines(choice.get("modifiers"), qty * portion, row.name):
			lines.append({**extra, "rpos_combo": row.item})
	return lines


def validate_item(doc, method=None) -> None:
	"""`Item.validate` — a combo the till can sell, or a refusal the manager can read."""
	if not doc.get("rpos_is_combo"):
		return
	if doc.is_stock_item:
		frappe.throw(_("A combo is not kept in stock; its items are. Untick Maintain Stock."))
	if doc.get("pos_modifier_groups"):
		frappe.throw(_("A combo asks its own choices. Remove its modifier groups."))
	if not doc.get("rpos_combo_items"):
		frappe.throw(_("Add the items this combo is made of."))

	defaults: dict[str, int] = {}
	for row in doc.rpos_combo_items:
		row.slot = (row.slot or "").strip()
		if not row.item:
			# `D-294` — «any item of the choice's group», which needs a group to name.
			if not row.slot or not choice(row.slot).item_group:
				frappe.throw(
					_("Row #{0}: Choose an item, or a choice that has an item group.").format(row.idx)
				)
			row.is_default = 0
			continue
		if row.item == doc.name or frappe.db.get_value("Item", row.item, "rpos_is_combo"):
			frappe.throw(_("Row #{0}: A combo cannot hold a combo.").format(row.idx))
		sellable = frappe.db.get_value("Item", row.item, ["is_sales_item", "disabled"], as_dict=True)
		if not sellable or not sellable.is_sales_item or sellable.disabled:
			frappe.throw(_("Row #{0}: {1} is not an enabled sales item.").format(row.idx, row.item))
		if not row.slot:
			row.is_default = 0
			row.adds_to_price = 0
		elif row.is_default:
			defaults[row.slot] = defaults.get(row.slot, 0) + 1
			most = cint(choice(row.slot).max_selections)
			if most and defaults[row.slot] > most:
				frappe.throw(_("{0} can have at most {1} default items.").format(row.slot, most))


def _display_name(item: str) -> str:
	return frappe.db.get_value("Item", item, "pos_display_name_ar") or frappe.db.get_value(
		"Item", item, "item_name"
	)

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
from frappe.utils import flt

from restaurant_pos.utils import addons

#: A combo's choices travel as modifier groups named ``combo:<combo>:<choice>``,
#: which no real group can be called (a group is named by its title).
PREFIX = "combo:"

#: The effect a combo's item carries on the order line — neither an add-on sold
#: under a dish nor one left out of its recipe, but the thing being sold.
EFFECT = "combo"


def is_combo(item: str) -> bool:
	return bool(frappe.db.get_value("Item", item, "rpos_is_combo"))


def definition(item: str) -> frappe._dict | None:
	if not is_combo(item):
		return None
	return frappe._dict(
		pricing=frappe.db.get_value("Item", item, "rpos_combo_pricing") or "fixed",
		rows=frappe.get_all(
			"POS Combo Item",
			filters={"parent": item, "parenttype": "Item"},
			fields=["slot", "item", "qty", "price_source", "price", "is_default", "adds_to_price"],
			order_by="idx",
		),
	)


def group_name(combo: str, slot: str) -> str:
	return f"{PREFIX}{combo}:{slot}"


def _list_price(item: str, price_list: str | None) -> float | None:
	if not price_list:
		return None
	rate = frappe.db.get_value(
		"Item Price", {"item_code": item, "price_list": price_list, "selling": 1}, "price_list_rate"
	)
	return None if rate is None else flt(rate)


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
		group = groups.setdefault(
			row.slot,
			{
				"name": group_name(combo, row.slot),
				"title": row.slot,
				"title_ar": row.slot,
				"selection_type": "single",
				"is_required": 1,
				"min_selections": 1,
				"max_selections": 1,
				"options": [],
			},
		)
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
	"""The groups the till opens for this combo, in the order the rows list them."""
	spec = definition(combo)
	seen: list[str] = []
	for row in spec.rows if spec else []:
		if row.slot and row.slot not in seen:
			seen.append(row.slot)
	return [group_name(combo, slot) for slot in seen]


def resolve(combo: str, selected: list | None, price_list: str | None) -> tuple[list, float]:
	"""The items a combo line sells, from the choices the till sent (FR-4.2).

	**One item per choice, from that choice's rows**, and every fixed item with
	it. Prices are read here, never taken from the client (`D-020`). Each entry
	keeps the item's own price as ``weight`` — what the invoice shares the
	combo's price by.
	"""
	spec = definition(combo)
	picked: dict[str, str] = {}
	for choice in selected or []:
		group = choice.get("group") or ""
		if not group.startswith(group_name(combo, "")):
			frappe.throw(_("{0} is not one of this combo's choices.").format(group))
		slot = group[len(group_name(combo, "")) :]
		if slot in picked:
			frappe.throw(_("Choose one item for {0}.").format(slot))
		picked[slot] = choice.get("option")

	resolved, delta = [], 0.0
	slots = {row.slot for row in spec.rows if row.slot}
	missing = sorted(slots - set(picked))
	if missing:
		frappe.throw(_("Choose: {0}").format("، ".join(missing)))

	for row in spec.rows:
		if row.slot and picked.get(row.slot) != row.item:
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
		slot
		for slot, item in picked.items()
		if not any(e["item"] == item and e["group"] == slot for e in resolved)
	]
	if unknown:
		frappe.throw(_("{0} is not offered under {1}.").format(picked[unknown[0]], unknown[0]))
	return resolved, delta


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
	weights = [flt(c.get("weight")) for c in items]
	total = sum(weights)
	if not total:
		weights, total = [1.0] * len(items), float(len(items))

	lines, given = [], 0.0
	for index, (choice, weight) in enumerate(zip(items, weights, strict=True)):
		share = flt(unit - given, 2) if index == len(items) - 1 else flt(unit * weight / total, 2)
		given += share
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
		lines.append(line)
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
			if defaults[row.slot] > 1:
				frappe.throw(_("{0} can have only one default item.").format(row.slot))


def _display_name(item: str) -> str:
	return frappe.db.get_value("Item", item, "pos_display_name_ar") or frappe.db.get_value(
		"Item", item, "item_name"
	)

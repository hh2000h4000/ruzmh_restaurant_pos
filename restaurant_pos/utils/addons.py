# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""An add-on tied to an item is sold like any item (`D-284`).

**«Extra cheese» is a slice of cheese leaving the fridge.** Until now a modifier
moved money and nothing else: the burger was billed at its dressed price and the
cheese never left stock, never cost anything, and never showed in a report.

Foodics links a modifier option to ingredients, Toast xtraCHEF maps it to a
product with a measured portion, and MarketMan depletes "extra cheese, no
onions" alongside the recipe. Here the option names an **item**, and that item
is sold the way every item is sold:

- **Sell** — its own line on the invoice, directly under its dish. ERPNext then
  does the rest with no arithmetic of ours: the stock leaves (the item itself,
  or its Product Bundle's recipe for a portion such as 0.15 kg of beef), the
  cost is booked, the revenue is its own and not the burger's, and a return
  brings it back. The till and the kitchen still see it under the dish.
- **Remove** — «no onion»: the dish's recipe leaves the ingredient out, so it
  does not leave stock. Toast's "Subtract" does the same to the recipe cost.

**Bound to the dish on the invoice** by the order line both came from, so a
return of the dish returns its add-ons with it — the guest returns a plate, not
a slice.

Refs: FR-4.2, D-281, D-284
"""

import json

import frappe
from frappe.utils import flt


def chosen(modifiers) -> list[dict]:
	"""The choices stored on an order line (`_resolve_modifiers`)."""
	if not modifiers:
		return []
	try:
		parsed = json.loads(modifiers) if isinstance(modifiers, str) else modifiers
	except ValueError:
		return []
	return parsed if isinstance(parsed, list) else []


def invoice_lines(row) -> list[dict]:
	"""The invoice lines for one order line: the dish, then each add-on it sells.

	**The money is the order's, split — not re-priced.** The line's amount holds
	the dish and every choice on it; each sold add-on takes the price it was rung
	at, and the dish keeps the rest, including anything a choice took off it.
	The bill's total is therefore exactly what the till showed, and a discount
	on it is spread over the lines by ERPNext in proportion to their value.
	"""
	qty = flt(row.qty)
	unit = flt(row.amount) / qty if qty else flt(row.rate)
	choices = chosen(row.modifiers)
	sold = [choice for choice in choices if choice.get("item") and choice.get("item_effect") == "sell"]
	removed = sorted(
		{choice["item"] for choice in choices if choice.get("item") and choice.get("item_effect") == "remove"}
	)

	lines = [
		{
			"item_code": row.item,
			"qty": qty,
			"rate": unit - sum(flt(choice.get("amount")) for choice in sold),
			"rpos_order_item": row.name,
			"rpos_removed": json.dumps(removed) if removed else None,
		}
	]
	for choice in sold:
		lines.append(
			{
				"item_code": choice["item"],
				"qty": qty,
				"rate": flt(choice.get("amount")),
				"rpos_order_item": row.name,
				"rpos_is_addon": 1,
			}
		)
	return lines


def leave_out_removed(doc, method=None) -> None:
	"""`Sales Invoice.validate` — «no onion» keeps the onion in the fridge.

	Runs after the controller's own `validate`, which is where ERPNext unpacks a
	dish's recipe into `packed_items` — and it unpacks it afresh on every save,
	so the removal is applied every time too. On a credit note the recipe is
	unpacked from the dish again, so the return leaves the onion out as the
	sale did.
	"""
	gone = {
		row.name: set(json.loads(row.rpos_removed)) for row in doc.get("items") if row.get("rpos_removed")
	}
	if not gone or not doc.get("packed_items"):
		return

	kept = [
		packed
		for packed in doc.packed_items
		if packed.item_code not in gone.get(packed.parent_detail_docname, ())
	]
	if len(kept) == len(doc.packed_items):
		return
	for idx, packed in enumerate(kept, start=1):
		packed.idx = idx
	doc.set("packed_items", kept)


def dish_rows(rows: list) -> list:
	"""The lines a guest sees on the bill: each dish, carrying its add-ons' money.

	An add-on row is folded into its dish, so the return screen offers the
	burger at what the guest paid for it — cheese and all — and never the cheese
	on its own.
	"""
	dishes = [row for row in rows if not row.get("rpos_is_addon")]
	by_line = {row.rpos_order_item: row for row in dishes if row.get("rpos_order_item")}
	for row in rows:
		if row.get("rpos_is_addon") and by_line.get(row.rpos_order_item):
			dish = by_line[row.rpos_order_item]
			dish.rate = flt(dish.rate) + flt(row.rate)
			dish.amount = flt(dish.amount) + flt(row.amount)
	return dishes


def with_addons(invoice: str, wanted: dict[str, float]) -> dict[str, float]:
	"""A dish coming back brings its add-ons, in the same share of the line."""
	rows = frappe.get_all(
		"Sales Invoice Item",
		filters={"parent": invoice, "parenttype": "Sales Invoice"},
		fields=["name", "qty", "rpos_order_item", "rpos_is_addon"],
	)
	dishes = {row.rpos_order_item: row for row in rows if row.rpos_order_item and not row.rpos_is_addon}

	full = dict(wanted)
	for row in rows:
		dish = dishes.get(row.rpos_order_item) if row.rpos_is_addon else None
		if dish and wanted.get(dish.name) and flt(dish.qty):
			full[row.name] = flt(wanted[dish.name]) * flt(row.qty) / flt(dish.qty)
	return full

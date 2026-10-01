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

#: The unit an add-on is sold in when one choice is not one stock unit (0.02 kg
#: of sauce is one portion). Created by `setup.install`.
PORTION = "Portion"


def chosen(modifiers) -> list[dict]:
	"""The choices stored on an order line (`_resolve_modifiers`)."""
	if not modifiers:
		return []
	try:
		parsed = json.loads(modifiers) if isinstance(modifiers, str) else modifiers
	except ValueError:
		return []
	return parsed if isinstance(parsed, list) else []


def list_price(item: str, price_list: str | None) -> float | None:
	"""An item's price for one unit of stock — the unit an add-on's quantity is in.

	A price list may hold the item's price in another unit — a carton of cans for
	a can — and read as it is, one choice would cost a carton. A price in the
	stock unit is taken as it is; one in another unit is divided by that unit's
	conversion factor on the item. None when the list has no price for it.
	"""
	if not price_list:
		return None
	prices = frappe.get_all(
		"Item Price",
		filters={"item_code": item, "price_list": price_list, "selling": 1},
		fields=["price_list_rate", "uom"],
	)
	stock_uom = frappe.db.get_value("Item", item, "stock_uom")
	for price in prices:
		if not price.uom or price.uom == stock_uom:
			return flt(price.price_list_rate)
	for price in prices:
		factor = frappe.db.get_value(
			"UOM Conversion Detail",
			{"parent": item, "parenttype": "Item", "uom": price.uom},
			"conversion_factor",
		)
		if flt(factor):
			return flt(price.price_list_rate) / flt(factor)
	return None


def portion_price(item: str, portion, price_list: str | None) -> float | None:
	"""An add-on priced from its item: the item's price on the list, per portion.

	The owner's water: «اضافة ماء» at the water's own 3.00, with nothing typed on
	the option (`D-284`). Per stock unit times the portion, so 0.02 kg of a
	sauce listed at 150.00 a kilo is 3.00. None when the list has no price —
	said to the cashier, never sold at nothing.
	"""
	rate = list_price(item, price_list)
	if rate is None:
		return None
	return flt(rate * (flt(portion) or 1), 2)


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
	removed = removed_items(choices)
	return [
		{
			"item_code": row.item,
			"qty": qty,
			"rate": unit - sum(flt(choice.get("amount")) for choice in _sold(choices)),
			"rpos_order_item": row.name,
			"rpos_removed": json.dumps(removed) if removed else None,
		},
		*sold_lines(choices, qty, row.name),
	]


def _sold(choices) -> list[dict]:
	return [
		choice for choice in chosen(choices) if choice.get("item") and choice.get("item_effect") == "sell"
	]


def removed_items(choices) -> list[str]:
	"""The ingredients «without» leaves out of a dish's recipe."""
	return sorted(
		{
			choice["item"]
			for choice in chosen(choices)
			if choice.get("item") and choice.get("item_effect") == "remove"
		}
	)


def sold_lines(choices, qty: float, order_item: str) -> list[dict]:
	"""An invoice line for each add-on sold with `qty` of a dish — or of a combo's item (`D-289`)."""
	lines = []
	for choice in _sold(choices):
		line = {
			"item_code": choice["item"],
			"qty": qty,
			"rate": flt(choice.get("amount")),
			"rpos_order_item": order_item,
			"rpos_is_addon": 1,
		}
		if not line["rate"]:
			# **Free, and said so in ERPNext's own words** — not a discount. A rate
			# of 0 reads to it as "none given" and it fills in the price list (the
			# owner's free water billed at 3.00), so the list price is 0 too; and
			# `is_free_item` is its flag for an item given away, which its
			# selling-price check lets through.
			line.update({"price_list_rate": 0, "is_free_item": 1})
		portion = flt(choice.get("item_qty")) or 1
		if portion != 1:
			# **Sold by the portion, taken from stock by the kilo** — ERPNext's
			# own sales-unit/stock-unit split. One portion at the option's price,
			# so the money stays exact to the halala, and 0.02 kg leaves the
			# warehouse because the conversion factor says so.
			line.update({"uom": PORTION, "conversion_factor": portion})
		lines.append(line)
	return lines


def stock_taken(row) -> dict[str, float]:
	"""What the add-ons sold on one order line take from stock, in stock units."""
	taken: dict[str, float] = {}
	for choice in chosen(row.modifiers):
		# A combo's items (`D-285`) leave stock the same way an add-on does, and
		# so do their own add-ons (`D-289`).
		if choice.get("item") and choice.get("item_effect") in ("sell", "combo"):
			qty = flt(row.qty) * (flt(choice.get("item_qty")) or 1)
			taken[choice["item"]] = taken.get(choice["item"], 0.0) + qty
			for extra in _sold(choice.get("modifiers")):
				more = qty * (flt(extra.get("item_qty")) or 1)
				taken[extra["item"]] = taken.get(extra["item"], 0.0) + more
	return taken


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
	on its own. **A combo's items fold the same way** (`D-285`), into one row
	named for the combo: the guest returns a meal.

	The rows of one order line share `rpos_order_item`; the first of them leads.
	"""
	leads: dict[str, object] = {}
	shown = []
	for row in sorted(rows, key=lambda row: row.get("idx") or 0):
		key = row.get("rpos_order_item")
		lead = leads.get(key) if key else None
		if lead is None:
			if key:
				leads[key] = row
			if row.get("rpos_combo"):
				row.item_code = row.rpos_combo
				row.item_name = frappe.db.get_value("Item", row.rpos_combo, "pos_display_name_ar") or (
					frappe.db.get_value("Item", row.rpos_combo, "item_name")
				)
			shown.append(row)
			continue
		lead.rate = flt(lead.rate) + flt(row.rate)
		lead.amount = flt(lead.amount) + flt(row.amount)
	return shown


def with_addons(invoice: str, wanted: dict[str, float]) -> dict[str, float]:
	"""A dish coming back brings its add-ons — a combo, its items — in the same share."""
	rows = frappe.get_all(
		"Sales Invoice Item",
		filters={"parent": invoice, "parenttype": "Sales Invoice"},
		fields=["name", "qty", "rpos_order_item"],
		order_by="idx",
	)
	leads: dict[str, object] = {}
	full = dict(wanted)
	for row in rows:
		if not row.rpos_order_item:
			continue
		lead = leads.setdefault(row.rpos_order_item, row)
		if lead is not row and wanted.get(lead.name) and flt(lead.qty):
			full[row.name] = flt(wanted[lead.name]) * flt(row.qty) / flt(lead.qty)
	return full

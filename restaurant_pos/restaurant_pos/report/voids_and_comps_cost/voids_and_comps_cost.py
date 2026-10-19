# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The food a restaurant paid for and was not paid for (`D-288`).

Square's comps and voids report puts it plainly: a comp is an item removed
from the bill **after** it was made or served, and «comps count against
inventory and can skew food costs»; a void is one removed before it was made.
Toast reads voided items and waste the same way. So the cost that matters is:

- **Voided after the kitchen** — cooked and thrown away. It was never sold, so
  **it never left stock**: the count finds it missing, and it lands in the
  variance of `Actual vs Theoretical Usage` (`D-287`). Its cost is what its
  recipe would have taken, at today's valuation — the only figure there is.
- **Given free** — sold at nothing: a free add-on, a zero-priced item. It **did**
  leave stock with its sale, so it is inside theoretical usage already; its cost
  is the one the books recorded.

A void before the kitchen cost nothing — nothing was made — and is left out;
`Sales Exceptions` lists it with the rest of the money.

Refs: FR-11.2, D-253, D-281, D-284, D-285, D-287, D-288
"""

import frappe
from frappe import _
from frappe.utils import flt

from restaurant_pos.restaurant_pos.report.item_sales import item_sales
from restaurant_pos.utils import addons, combos, reporting
from restaurant_pos.utils.bulk import get_all_in

VOIDED = "voided_after_kitchen"
FREE = "free"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date, to_date = reporting.window(filters)

	rows: dict[tuple, dict] = {}
	for kind, item, reason, qty, cost in [
		*_voids(filters, from_date, to_date),
		*_comps(filters, from_date, to_date),
	]:
		row = rows.setdefault(
			(kind, item, reason),
			{"kind": _kind_label(kind), "item_code": item, "reason": reason, "qty": 0.0, "cost": 0.0},
		)
		row["qty"] += flt(qty)
		row["cost"] += flt(cost)

	shown = sorted(rows.values(), key=lambda row: row["cost"], reverse=True)
	for row in shown:
		row["cost"] = flt(row["cost"], 2)
	message = _(
		"Voided after the kitchen never left stock: the next count finds it missing. "
		"Free items did, with their sale."
	)
	return _columns(), shown, message if shown else None


def _kind_label(kind: str) -> str:
	return _("Voided after the kitchen") if kind == VOIDED else _("Given free")


# --------------------------------------------------------------------------- #
# Voided after the kitchen
# --------------------------------------------------------------------------- #


def _voids(filters, from_date: str, to_date: str) -> list[tuple]:
	lines = frappe.get_all(
		"Restaurant Order Item",
		filters={
			"parenttype": "Restaurant Order",
			"status": "void",
			"sent_at": ("is", "set"),
			"voided_at": ("between", [from_date, to_date]),
		},
		fields=["parent", "item", "qty", "modifiers", "void_reason"],
	)
	if not lines:
		return []

	orders = {
		row.name: row.pos_profile
		for row in get_all_in(
			"Restaurant Order",
			filters={**reporting.scope(filters), "name": ("in", list({line.parent for line in lines}))},
			fields=["name", "pos_profile"],
		)
	}
	found = []
	for line in lines:
		if line.parent not in orders:
			continue
		warehouse = frappe.db.get_value("POS Profile", orders[line.parent], "warehouse")
		found.append((VOIDED, line.item, line.void_reason or "", line.qty, _line_cost(line, warehouse)))
	return found


def _line_cost(line, warehouse: str | None) -> float:
	"""What an order line would have taken from stock: its recipe, add-ons and combo items."""
	qty = flt(line.qty)
	parts = combos.parts(line)
	if parts:
		# `D-289` — each item with its own add-ons and «without», as a dish.
		return sum(
			_dish_cost(p["item"], qty * (flt(p.get("item_qty")) or 1), p.get("modifiers"), warehouse)
			for p in parts
		)
	return _dish_cost(line.item, qty, line.modifiers, warehouse)


def _dish_cost(item: str, qty: float, modifiers, warehouse: str | None) -> float:
	cost = _item_cost(item, qty, warehouse, set(addons.removed_items(modifiers)))
	for choice in addons.chosen(modifiers):
		if choice.get("item") and choice.get("item_effect") == "sell":
			cost += _item_cost(choice["item"], qty * (flt(choice.get("item_qty")) or 1), warehouse)
	return cost


def _item_cost(item: str, qty: float, warehouse: str | None, removed: set | frozenset = frozenset()) -> float:
	recipe = frappe.get_all(
		"Product Bundle Item",
		filters={"parent": item, "parenttype": "Product Bundle"},
		fields=["item_code", "qty"],
	)
	if recipe and frappe.db.get_value("Product Bundle", item, "disabled") == 0:
		return sum(
			_rate(part.item_code, warehouse) * flt(part.qty) * qty
			for part in recipe
			if part.item_code not in removed
		)
	if frappe.db.get_value("Item", item, "is_stock_item"):
		return _rate(item, warehouse) * qty
	return 0.0


def _rate(item: str, warehouse: str | None) -> float:
	"""Today's valuation in the till's warehouse, or the item's own when it has none there."""
	rate = warehouse and frappe.db.get_value(
		"Bin", {"item_code": item, "warehouse": warehouse}, "valuation_rate"
	)
	return flt(rate) or flt(frappe.db.get_value("Item", item, "valuation_rate"))


# --------------------------------------------------------------------------- #
# Given free
# --------------------------------------------------------------------------- #


def _comps(filters, from_date: str, to_date: str) -> list[tuple]:
	invoices = [
		row.sales_invoice for row in reporting.settled_orders(filters, from_date, to_date, ["sales_invoice"])
	]
	# A free item that came back with a refund went back to stock: its credit
	# note's line is negative in quantity and cost, and takes it off again.
	returned = reporting.credit_notes(filters, from_date, to_date)
	found = []
	for line in [*item_sales._lines_of(invoices, None), *item_sales._lines_of(returned, None)]:
		if not flt(line.qty) or flt(line.net_amount):
			continue
		cost = frappe._dict(cost=0.0, uncosted_qty=0.0, short_costed_qty=0.0)
		item_sales._add_cost(cost, line)
		found.append((FREE, line.item_code, "", line.qty, cost.cost))
	return found


def _columns() -> list[dict]:
	return [
		{"fieldname": "kind", "label": _("Kind", context="RPOS report"), "fieldtype": "Data", "width": 170},
		{
			"fieldname": "item_code",
			"label": _("Item", context="RPOS report"),
			"fieldtype": "Link",
			"options": "Item",
			"width": 220,
		},
		{
			"fieldname": "reason",
			"label": _("Reason", context="RPOS report"),
			"fieldtype": "Data",
			"width": 200,
		},
		{
			"fieldname": "qty",
			"label": _("Quantity", context="RPOS report"),
			"fieldtype": "Float",
			"width": 100,
		},
		{
			"fieldname": "cost",
			"label": _("Cost", context="RPOS report"),
			"fieldtype": "Currency",
			"width": 130,
		},
	]

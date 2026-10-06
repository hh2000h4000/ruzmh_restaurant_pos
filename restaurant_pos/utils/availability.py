# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""How many of a thing sold as it came are left to sell (`D-321`).

**Only what is kept in stock as itself** — a bottle of water, a can of juice.
A dish with a recipe is not counted from its ingredients: a restaurant's
ingredient stock is never right to the minute (the delivery is on the shelf
before its receipt is in the books, the cook's hand is not the recipe's), and a
till that refuses a burger because the ledger says the beef is gone, with the
beef in the fridge, stops a queue for nothing. Toast and Foodics deplete
ingredients for the reports and leave the dish to a person — the "sold out"
mark — and so does this. A bottle is different: its number is the bottle's own,
and ERPNext's own POS shows it.

    left = on the shelf  -  sold and not posted yet  -  on bills still open

The middle term is why this is not ERPNext's check. A till sale reaches the
stock ledger when its day is posted (`D-313`), so the shelf alone overstates
what is left by everything sold since — and ERPNext's `get_pos_reserved_qty`,
which knows that, reads every POS Invoice ever made (28 s over 200,000 on the
rehearsal site, `docs/14` §5.4). This reads only what is not posted, through the
index the posting itself claims by.

**Information for the screen, a decision at the bill.** The till shows a number
that may be seconds old (`for_terminal`, cached); the refusal reads it fresh, for
the one item asked for (`assert_can_sell`). No lock: two tills racing for the
last bottle may both get it, and the shortfall shows at posting (`docs/14` §5.0).

Refs: `docs/14_POS_Posting_Design.md` §5
"""

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import cint, flt

from restaurant_pos.utils.sale_doc import SALE, SALE_ITEM, WASTED

#: How long one branch's figures are shared between its tills.
SHARED_FOR_SECONDS = 15

#: A bill in any of these still holds what is on it.
OPEN = ("draft", "active", "in_kitchen", "pending_payment")


def is_enforced(branch: str) -> bool:
	"""Does this branch refuse a sale its stock cannot cover?"""
	return bool(cint(frappe.get_cached_value("Branch", branch, "rpos_enforce_stock")))


def for_terminal(pos_profile: str) -> dict[str, float]:
	"""item -> how many are left, for everything this terminal sells as it came.

	Shared by the branch's tills for a few seconds: ten of them opening at once
	are one reading, and a number on a tile does not need to be newer than that.
	"""
	branch, warehouse = _place(pos_profile)
	if not warehouse:
		return {}

	key = f"rpos_left::{branch}::{warehouse}"
	left = frappe.cache().get_value(key)
	if left is None:
		left = left_in(branch, warehouse)
		frappe.cache().set_value(key, left, expires_in_sec=SHARED_FOR_SECONDS)
	return left


def assert_can_sell(order, item: str, more: float) -> None:
	"""Refuse ``more`` of ``item`` on this bill when an enforcing branch has fewer left.

	Asked when the line is added or raised — never at payment: by then the
	guest has eaten, and a bill that cannot close helps nobody.
	"""
	if flt(more) <= 0 or not is_enforced(order.branch):
		return

	_branch, warehouse = _place(order.pos_profile)
	left = left_in(order.branch, warehouse, items=[item]) if warehouse else {}
	if item not in left:
		# Not kept in stock as itself: a dish, a service, a combo.
		return

	if left[item] + 1e-9 >= flt(more):
		return

	name = frappe.get_cached_value("Item", item, "pos_display_name_ar") or frappe.get_cached_value(
		"Item", item, "item_name"
	)
	if left[item] <= 0:
		frappe.throw(_("{0} is sold out.").format(name))
	frappe.throw(_("Only {0} of {1} left.").format(f"{left[item]:g}", name))


def left_in(branch: str, warehouse: str, items: list[str] | None = None) -> dict[str, float]:
	"""Read it now. Four indexed queries, whatever the size of the menu or the history."""
	stocked = frappe.get_all(
		"Item",
		filters={
			"is_stock_item": 1,
			"is_sales_item": 1,
			"disabled": 0,
			**({"name": ("in", items)} if items else {}),
		},
		pluck="name",
	)
	if not stocked:
		return {}

	left = dict.fromkeys(stocked, 0.0)
	for item, qty in frappe.get_all(
		"Bin",
		filters={"warehouse": warehouse, **({"item_code": ("in", items)} if items else {})},
		fields=["item_code", "actual_qty"],
		as_list=True,
	):
		if item in left:
			left[item] = flt(qty)

	for item, qty in _sold_and_not_posted(branch, warehouse, items) + _on_open_bills(
		branch, warehouse, items
	):
		if item in left:
			left[item] -= flt(qty)
	return left


def _place(pos_profile: str) -> tuple[str | None, str | None]:
	"""(branch, the warehouse this terminal sells from)."""
	from restaurant_pos.utils.order import branch_of_profile

	return branch_of_profile(pos_profile), frappe.get_cached_value("POS Profile", pos_profile, "warehouse")


def _sold_and_not_posted(branch: str, warehouse: str, items: list[str] | None) -> list[tuple]:
	"""(item, quantity) taken by bills the posting has not claimed — as a line, or inside a recipe."""
	invoice = frappe.qb.DocType(SALE)
	unposted = (
		frappe.qb.from_(invoice)
		.select(invoice.name)
		.where(
			(invoice.rpos_branch == branch)
			& (invoice.docstatus == 1)
			& (invoice.rpos_posting_batch.isnull() | (invoice.rpos_posting_batch == ""))
		)
	)

	line = frappe.qb.DocType(SALE_ITEM)
	lines = (
		frappe.qb.from_(line)
		.select(line.item_code, Sum(line.stock_qty))
		# A return that was thrown away puts nothing back (`D-315`).
		.where(line.parent.isin(unposted) & (line.warehouse == warehouse) & (line[WASTED] == 0))
		.groupby(line.item_code)
	)
	packed = frappe.qb.DocType("Packed Item")
	recipe = (
		frappe.qb.from_(packed)
		.select(packed.item_code, Sum(packed.qty))
		.where(packed.parent.isin(unposted) & (packed.parenttype == SALE) & (packed.warehouse == warehouse))
		.groupby(packed.item_code)
	)
	if items:
		lines = lines.where(line.item_code.isin(items))
		recipe = recipe.where(packed.item_code.isin(items))
	return list(lines.run()) + list(recipe.run())


def _on_open_bills(branch: str, warehouse: str, items: list[str] | None) -> list[tuple]:
	"""(item, quantity) on bills not paid yet: the bottle on table four is not on the shelf."""
	terminals = frappe.get_all("POS Profile", filters={"warehouse": warehouse}, pluck="name")
	if not terminals:
		return []

	order = frappe.qb.DocType("Restaurant Order")
	row = frappe.qb.DocType("Restaurant Order Item")
	query = (
		frappe.qb.from_(row)
		.join(order)
		.on(order.name == row.parent)
		.select(row.item, Sum(row.qty))
		.where(
			(order.branch == branch)
			& order.status.isin(OPEN)
			& order.pos_profile.isin(terminals)
			& (row.status != "void")
		)
		.groupby(row.item)
	)
	if items:
		query = query.where(row.item.isin(items))
	return list(query.run())

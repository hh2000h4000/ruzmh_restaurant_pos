# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Which dishes sold, over a stretch of days — the report an owner reads weekly.

**ERPNext already has the register, and this is not it.** `Item-wise Sales
Register` prints one row per invoice line, over every invoice in the company,
with no notion of a branch or an order type — a thousand rows that answer "what
was on invoice 412", not "what does this restaurant sell". The question here is
the other one: one row per dish, ranked, with its share of the takings. Foodics
calls it the product mix and it is the first screen a restaurant owner opens.

**Amounts exclude VAT.** `net_amount` is the ex-tax figure whether the branch
prices tax-inclusive (`D-091`) or not, so the same column means the same thing
across branches, and it is the number a food cost is compared against.

**Cost is asked for, not assumed** (`D-244`). `incoming_rate` is what the stock
was worth when the dish left it — ERPNext's own gross profit reads the same
figure — but a restaurant running without stock has none, and a margin column
reading 100% on every line is a lie told in a currency. So the columns appear
only when the owner ticks for them, and lines with no cost are counted and said
aloud rather than passed off as free to make.

**A combo reads two ways** (`D-286`). By default its burger and its drink are
counted where they belong — Square's item sales do the same — and a column says
how many of each went out inside a combo. Ticked «combos as meals», each combo
is one row instead: how many meals, what they brought in, what they cost. Never
both at once, or the meal's money would be counted twice.

Refs: FR-11.2, D-217, D-243, D-244, D-285, D-286
"""

import frappe
from frappe import _
from frappe.utils import flt

from restaurant_pos.utils import posting, reporting
from restaurant_pos.utils.sale_doc import LINE_COST, SALE, SALE_ITEM, WASTED


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date, to_date = reporting.window(filters)
	by_group = bool(filters.group_by_item_group)
	costed = bool(filters.show_cost)
	meals = bool(filters.combos_as_meals)

	orders = reporting.settled_orders(filters, from_date, to_date, ["sales_invoice"])
	sold = _lines_of([row.sales_invoice for row in orders], filters.item_group)
	returned = _lines_of(reporting.credit_notes(filters, from_date, to_date), filters.item_group)

	rows = _tally(sold, returned, by_group=by_group, meals=meals)
	rows = [row for row in rows if row["qty"] or row["returned_qty"]]
	rows.sort(key=lambda row: row["amount"], reverse=True)

	total = sum(row["amount"] for row in rows)
	for row in rows:
		row["share"] = flt(row["amount"] / total * 100, 2) if total else 0.0
		if costed:
			_cost_columns(row)

	return (
		_columns(by_group=by_group, costed=costed, meals=meals),
		rows,
		(_message(rows) if costed else None),
	)


# --------------------------------------------------------------------------- #
# Lines
# --------------------------------------------------------------------------- #


def _lines_of(invoices: list[str], item_group: str | None) -> list[frappe._dict]:
	if not invoices:
		return []

	filters = {"parent": ("in", invoices), "docstatus": 1}
	if item_group:
		filters["item_group"] = item_group

	lines = frappe.get_all(
		SALE_ITEM,
		filters=filters,
		fields=[
			"name",
			"parent",
			"item_code",
			"item_name",
			"item_group",
			"rpos_combo",
			"rpos_order_item",
			"qty",
			"stock_qty",
			"net_amount",
			"warehouse",
			# Stamped by the posting that took the line from the warehouse
			# (`D-314`): nothing until the sale's day is posted.
			f"{LINE_COST} as incoming_rate",
			WASTED,
		],
	)
	posted = _with_their_cost_written(invoices)
	recipe_rows = frappe.get_all(
		"Packed Item",
		filters={"parenttype": SALE, "parent": ("in", invoices)},
		fields=["parent", "parent_detail_docname", "item_code", "warehouse", "qty", "incoming_rate"],
	)
	expected = _expected_rates([row for row in lines + recipe_rows if row.parent not in posted])
	for row in recipe_rows:
		if row.parent not in posted:
			row.incoming_rate = expected(row.item_code, row.warehouse)

	recipes = _recipe_costs(recipe_rows)
	for line in lines:
		line.posted = line.parent in posted
		if not line.posted:
			line.incoming_rate = expected(line.item_code, line.warehouse)
		if line.name in recipes:
			line.recipe_cost, line.recipe_short = recipes[line.name]
	return lines


def _expected_rates(waiting: list):
	"""What a sale not posted yet is expected to cost: today's valuation (`D-324`).

	The owner's question: yesterday's burger was posted and has its cost — why
	should today's show none? **It is priced the way the posting will price it**:
	what the warehouse values the item at now, or the rate on the item's card
	for something kept without stock. Not yesterday's figure copied forward —
	the warehouse's current one, which already has yesterday in it and this
	morning's delivery too. The actual cost replaces it when the day is posted,
	and differs only by what was bought in between.

	Returns ``rate(item, warehouse)``.
	"""
	items = list({row.item_code for row in waiting})
	if not items:
		return lambda item, warehouse: 0.0

	shelf = {
		(row.item_code, row.warehouse): flt(row.valuation_rate)
		for row in frappe.get_all(
			"Bin",
			filters={
				"item_code": ("in", items),
				"warehouse": ("in", list({row.warehouse for row in waiting if row.warehouse})),
			},
			fields=["item_code", "warehouse", "valuation_rate"],
		)
	}
	card = dict(
		frappe.get_all(
			"Item", filters={"name": ("in", items)}, fields=["name", "valuation_rate"], as_list=True
		)
	)
	return lambda item, warehouse: shelf.get((item, warehouse)) or flt(card.get(item))


def _with_their_cost_written(invoices: list[str]) -> set[str]:
	"""The bills whose stock has been posted — the only ones that know what they cost.

	**Today's sales have no cost yet, and that is not "no cost"** (`D-323`). A
	sale's cost is written when its day is posted (`D-314`); until then the
	line is blank because nobody has asked the warehouse, not because the dish
	is free. Read as uncosted, every dish sold today showed a full-price profit
	until the day was closed. The rest carry an expected cost (`D-324`).
	"""
	done = frappe.get_all(posting.BATCH, filters={"stock_status": ("in", posting.DONE)}, pluck="name")
	if not done:
		return set()
	return set(
		frappe.get_all(
			SALE, filters={"name": ("in", invoices), "rpos_posting_batch": ("in", done)}, pluck="name"
		)
	)


def _recipe_costs(recipe_rows: list) -> dict[str, tuple[float, bool]]:
	"""What a dish sold by its recipe cost — the sum of its ingredients (`D-281`).

	A prepared dish is not a stock item, so its own line carries no cost: the
	invoice unpacks its Product Bundle into packed items, and **those** leave the
	warehouse at a worth. Read off the line alone, every burger was free to make
	— the owner's question was exactly this: «أصناف غير مخزنة… ويحسب تكلفتها من
	مكوناتها».

	**An ingredient with no worth counts as nothing, and the rest still count**
	(`D-282`). Calling the whole burger uncosted because the bun had no price
	threw away three prices that were known — the owner: «الأفضل تطلع التكلفة
	تكلفة باقي المكونات». The second value says a line was short an ingredient,
	so the report can say its cost reads low.
	"""
	costs: dict[str, tuple[float, bool]] = {}
	for packed in recipe_rows:
		cost, short = costs.get(packed.parent_detail_docname, (0.0, False))
		rate = flt(packed.incoming_rate)
		costs[packed.parent_detail_docname] = (cost + abs(flt(packed.qty)) * rate, short or not rate)
	return costs


# --------------------------------------------------------------------------- #
# Tally
# --------------------------------------------------------------------------- #


def _tally(sold: list, returned: list, *, by_group: bool, meals: bool = False) -> list[dict]:
	"""One row per dish, or per group when the manager asks the coarser question."""
	rows: dict[str, dict] = {}
	if meals:
		sold, returned = _as_meals(sold), _as_meals(returned)

	def row_for(line) -> dict:
		key = line.item_group if by_group else line.item_code
		return rows.setdefault(
			key or "",
			{
				"item_group": line.item_group,
				"qty": 0.0,
				"returned_qty": 0.0,
				"net_qty": 0.0,
				"amount": 0.0,
				"cost": 0.0,
				"uncosted_qty": 0.0,
				"short_costed_qty": 0.0,
				"expected_qty": 0.0,
				"combo_qty": 0.0,
			}
			# `item_name` carries no column: Frappe's Link cell reads it from the row
			# and prints "CODE: Name", so a column of its own would repeat the words.
			| ({} if by_group else {"item_code": line.item_code, "item_name": line.item_name}),
		)

	for line in sold:
		row = row_for(line)
		row["qty"] += flt(line.qty)
		row["amount"] += flt(line.net_amount)
		if line.get("rpos_combo"):
			row["combo_qty"] += flt(line.qty)
		_add_cost(row, line)

	# A credit note's own quantities and amounts are already negative, so the
	# returned column is their size and the takings — and the cost — simply add.
	for line in returned:
		row = row_for(line)
		row["returned_qty"] += abs(flt(line.qty))
		row["amount"] += flt(line.net_amount)
		_add_cost(row, line)

	for row in rows.values():
		row["net_qty"] = row["qty"] - row["returned_qty"]
		row["amount"] = flt(row["amount"], 2)

	return list(rows.values())


def _as_meals(lines: list) -> list:
	"""A combo's lines folded into one line per meal, named for the combo (`D-286`).

	Its items share one order line, so the meals are counted once per order
	line on each document; the money and the cost are the items' own, added.
	"""
	meals: dict[tuple, frappe._dict] = {}
	kept = []
	for line in lines:
		if not line.get("rpos_combo"):
			kept.append(line)
			continue
		key = (line.parent, line.rpos_order_item)
		meal = meals.get(key)
		if meal is None:
			combo = frappe.db.get_value(
				"Item", line.rpos_combo, ["item_name", "pos_display_name_ar", "item_group"], as_dict=True
			)
			meal = meals[key] = frappe._dict(
				item_code=line.rpos_combo,
				item_name=combo.pos_display_name_ar or combo.item_name,
				item_group=combo.item_group,
				qty=flt(line.qty),
				net_amount=0.0,
				recipe_cost=0.0,
				recipe_short=False,
				# One bill, one posting: its lines are all posted or none is.
				posted=line.posted,
			)
			kept.append(meal)
		meal.net_amount += flt(line.net_amount)
		cost = frappe._dict(cost=0.0, uncosted_qty=0.0, short_costed_qty=0.0, expected_qty=0.0)
		_add_cost(cost, line)
		# Kept positive like a recipe's cost; `_add_cost` gives it the credit note's sign.
		meal.recipe_cost += abs(cost.cost)
		meal.recipe_short = meal.recipe_short or bool(cost.short_costed_qty or cost.uncosted_qty)
	return kept


def _add_cost(row: dict, line) -> None:
	"""What the stock was worth as it left — and how much left with no worth at all."""
	if not line.posted:
		# Not posted yet: the cost below is the expected one (`D-324`), and the
		# report says how much of a row rests on it.
		row["expected_qty"] += abs(flt(line.qty))

	if line.get(WASTED):
		# Returned and thrown away (`D-315`): the money went back and the food did
		# not, so no cost comes back with it. It is waste, and the books say so.
		return

	if "recipe_cost" in line:
		# Sold adds its cost; a credit note, whose quantity is negative, takes it back.
		row["cost"] += line.recipe_cost if flt(line.qty) > 0 else -line.recipe_cost
		if line.recipe_short:
			row["short_costed_qty"] += abs(flt(line.qty))
		return

	# **Per stock unit, so times the stock quantity** — not the quantity sold,
	# which is in the unit it was sold in: an add-on of 0.02 kg of sauce is one
	# portion sold and 0.02 kg gone (`D-284`). The two are equal on every line
	# sold in its own stock unit.
	rate = flt(line.incoming_rate)
	if rate:
		row["cost"] += rate * flt(line.stock_qty if line.get("stock_qty") is not None else line.qty)
	else:
		row["uncosted_qty"] += abs(flt(line.qty))


def _cost_columns(row: dict) -> None:
	row["cost"] = flt(row["cost"], 2)
	row["profit"] = flt(row["amount"] - row["cost"], 2)
	row["margin"] = flt(row["profit"] / row["amount"] * 100, 2) if row["amount"] else 0.0
	# **The restaurant's own measure** (`D-282`): the Uniform System of Accounts
	# for Restaurants states food cost as cost of food sold over food sales —
	# the margin's complement, and the figure a kitchen is actually run on.
	row["cost_ratio"] = flt(row["cost"] / row["amount"] * 100, 2) if row["amount"] else 0.0


def _message(rows: list[dict]) -> str | None:
	"""Say it plainly when a margin is built on costs that are missing or short."""
	said = []
	waiting = [row for row in rows if row["expected_qty"]]
	if waiting:
		said.append(
			_(
				"{0} of {1} lines include sales not posted yet: their cost is the expected one, at today's "
				"valuation. The actual cost replaces it when their day is closed and posted."
			).format(len(waiting), len(rows))
		)
	blind = [row for row in rows if row["uncosted_qty"]]
	if blind:
		said.append(
			_("{0} of {1} lines have no cost, so their profit reads as the whole price.").format(
				len(blind), len(rows)
			)
		)
	short = [row for row in rows if row["short_costed_qty"]]
	if short:
		# Said as what the books hold, not as an error: ERPNext will not post an
		# ingredient with no valuation unless «Allow Zero Valuation Rate» was
		# ticked, so a zero here is the recorded cost (IAS 2 ¶34) — worth a look
		# in case the tick was a slip, not a figure to second-guess.
		said.append(
			_("{0} of {1} lines include an ingredient carried at zero cost in the books.").format(
				len(short), len(rows)
			)
		)
	return " ".join(said) or None


# --------------------------------------------------------------------------- #
# Columns
# --------------------------------------------------------------------------- #


def _columns(*, by_group: bool, costed: bool, meals: bool = False) -> list[dict]:
	item = {
		"fieldname": "item_code",
		"label": _("Item", context="RPOS report"),
		"fieldtype": "Link",
		"options": "Item",
		"width": 240,
	}
	group = {
		"fieldname": "item_group",
		"label": _("Item Group"),
		"fieldtype": "Link",
		"options": "Item Group",
		"width": 170,
	}

	money = [
		{"fieldname": "qty", "label": _("Sold"), "fieldtype": "Float", "width": 90},
		{
			"fieldname": "returned_qty",
			"label": _("Returned", context="RPOS report"),
			"fieldtype": "Float",
			"width": 100,
		},
		{"fieldname": "net_qty", "label": _("Net Quantity"), "fieldtype": "Float", "width": 110},
		# `D-286` — how many of the sold went out inside a combo.
		*(
			[]
			if meals
			else [
				{
					"fieldname": "combo_qty",
					"label": _("In Combos", context="RPOS report"),
					"fieldtype": "Float",
					"width": 110,
				}
			]
		),
		{"fieldname": "amount", "label": _("Sales (excl. VAT)"), "fieldtype": "Currency", "width": 150},
	]
	cost = [
		{
			"fieldname": "cost",
			"label": _("Cost", context="RPOS report"),
			"fieldtype": "Currency",
			"width": 130,
		},
		{"fieldname": "cost_ratio", "label": _("Food Cost %"), "fieldtype": "Float", "width": 110},
		{"fieldname": "profit", "label": _("Profit"), "fieldtype": "Currency", "width": 130},
		# **Float, not Percent**, for the same reason the share is: Frappe's total
		# row averages a percent column, and an average of margins is not a margin.
		{"fieldname": "margin", "label": _("Margin %"), "fieldtype": "Float", "width": 100},
	]
	share = {"fieldname": "share", "label": _("Share of Sales %"), "fieldtype": "Float", "width": 130}

	return ([group] if by_group else [item, group]) + money + (cost if costed else []) + [share]

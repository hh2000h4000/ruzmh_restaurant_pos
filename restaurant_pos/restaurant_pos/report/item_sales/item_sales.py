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

Refs: FR-11.2, D-217, D-243, D-244
"""

import frappe
from frappe import _
from frappe.utils import flt

from restaurant_pos.utils import reporting


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date, to_date = reporting.window(filters)
	by_group = bool(filters.group_by_item_group)
	costed = bool(filters.show_cost)

	orders = reporting.settled_orders(filters, from_date, to_date, ["sales_invoice"])
	sold = _lines_of([row.sales_invoice for row in orders], filters.item_group)
	returned = _lines_of(reporting.credit_notes(filters, from_date, to_date), filters.item_group)

	rows = _tally(sold, returned, by_group=by_group)
	rows = [row for row in rows if row["qty"] or row["returned_qty"]]
	rows.sort(key=lambda row: row["amount"], reverse=True)

	total = sum(row["amount"] for row in rows)
	for row in rows:
		row["share"] = flt(row["amount"] / total * 100, 2) if total else 0.0
		if costed:
			_cost_columns(row)

	return _columns(by_group=by_group, costed=costed), rows, (_message(rows) if costed else None)


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
		"Sales Invoice Item",
		filters=filters,
		fields=[
			"name",
			"item_code",
			"item_name",
			"item_group",
			"qty",
			"stock_qty",
			"net_amount",
			"incoming_rate",
		],
	)
	recipes = _recipe_costs(invoices)
	for line in lines:
		if line.name in recipes:
			line.recipe_cost, line.recipe_short = recipes[line.name]
	return lines


def _recipe_costs(invoices: list[str]) -> dict[str, tuple[float, bool]]:
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
	for packed in frappe.get_all(
		"Packed Item",
		filters={"parenttype": "Sales Invoice", "parent": ("in", invoices)},
		fields=["parent_detail_docname", "qty", "incoming_rate"],
	):
		cost, short = costs.get(packed.parent_detail_docname, (0.0, False))
		rate = flt(packed.incoming_rate)
		costs[packed.parent_detail_docname] = (cost + abs(flt(packed.qty)) * rate, short or not rate)
	return costs


# --------------------------------------------------------------------------- #
# Tally
# --------------------------------------------------------------------------- #


def _tally(sold: list, returned: list, *, by_group: bool) -> list[dict]:
	"""One row per dish, or per group when the manager asks the coarser question."""
	rows: dict[str, dict] = {}

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
			}
			# `item_name` carries no column: Frappe's Link cell reads it from the row
			# and prints "CODE: Name", so a column of its own would repeat the words.
			| ({} if by_group else {"item_code": line.item_code, "item_name": line.item_name}),
		)

	for line in sold:
		row = row_for(line)
		row["qty"] += flt(line.qty)
		row["amount"] += flt(line.net_amount)
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


def _add_cost(row: dict, line) -> None:
	"""What the stock was worth as it left — and how much left with no worth at all."""
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


def _columns(*, by_group: bool, costed: bool) -> list[dict]:
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

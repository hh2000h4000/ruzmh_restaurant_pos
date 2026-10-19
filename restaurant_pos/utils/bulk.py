# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Reading rows for a long list of names, at the cost of the list (`D-366`).

`frappe.get_all` re-parses every query it builds with `sqlparse` before running
it — a safety check Frappe added for list queries, with the token cap lifted for
long `IN (...)` lists. That parse grows far faster than the list: closing a day
of 2,370 bills spent **25 of its 26 seconds** parsing the summary's eight
queries, before the database saw any of them. A branch with twice the bills
would not close inside a request's time limit, and a customer's two-core
server would get there sooner.

The query builder writes the SQL from parts and has nothing to re-parse, so a
list of 2,370 names costs what 2,370 names cost. Used only where the list is
the size of a day or a period — the close, the posting, the reports
(`D-367`); everything else stays on `get_all`. Like `get_all`, it reads without
permission checks — these are server-side tallies behind the callers' own
guards.
"""

import frappe


def get_all_in(
	doctype: str,
	*,
	filters: dict,
	fields: list[str] | None = None,
	pluck: str | None = None,
	order_by: str | None = None,
) -> list:
	"""`get_all` for the filters a tally asks: a value, a comparison, a list, a range, set or not."""
	table = frappe.qb.DocType(doctype)
	wanted = [pluck] if pluck else (fields or ["name"])
	query = frappe.qb.from_(table).select(*(_column(table, field) for field in wanted))

	for field, value in filters.items():
		condition = _condition(table[field], value)
		if condition is None:
			# `in` an empty list matches nothing, as `get_all` answers it.
			return []
		query = query.where(condition)

	for part in (order_by or "").split(","):
		name, _space, direction = part.strip().partition(" ")
		if name:
			order = frappe.qb.desc if direction.strip().lower() == "desc" else frappe.qb.asc
			query = query.orderby(table[name], order=order)

	rows = query.run(as_dict=True)
	return [row[pluck] for row in rows] if pluck else rows


def _condition(column, value):
	operator, operand = value if isinstance(value, tuple | list) and len(value) == 2 else ("=", value)
	operator = operator.lower()
	if operator in ("in", "not in"):
		operand = list(operand or [])
		if not operand:
			return None if operator == "in" else column.isnotnull() | column.isnull()
		return column.isin(operand) if operator == "in" else column.notin(operand)
	if operator == "between":
		return column[operand[0] : operand[1]]
	if operator == "is":
		return (
			(column.isnotnull() & (column != "")) if operand == "set" else (column.isnull() | (column == ""))
		)
	if operator == "like":
		return column.like(operand)
	return {
		"=": column == operand,
		"!=": column != operand,
		"<": column < operand,
		"<=": column <= operand,
		">": column > operand,
		">=": column >= operand,
	}[operator]


def _column(table, field: str):
	"""A field, or `field as alias` the way `get_all` writes it."""
	name, _as, alias = field.partition(" as ")
	column = table[name.strip()]
	return column.as_(alias.strip()) if alias else column

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""What the kitchen used, against what its sales say it should have (`D-287`).

**The report a restaurant's food cost is run on.** Toast's xtraCHEF, MarginEdge
and MarketMan all build it the same way, between two physical counts:

- **actual** usage — opening count + what came in, less the closing count;
- **theoretical** usage — what the recipes of the dishes sold took;
- the **variance** between them — spoilage, mistakes, heavy portions, theft.

**Theoretical is already in the books here.** The till's invoice takes each
dish's recipe out of stock as it is sold (`D-281`, `D-284`, `D-285`), so what
sales used is the sales vouchers' own lines in the stock ledger — not a second
calculation that could disagree with it.

**The period runs from count to count**, as Toast requires. A count in ERPNext
is a Stock Reconciliation, which records the balance counted rather than the
change, so the variance is worked out from balances: after the opening count,
at the closing count, and every movement between. Without a closing count the
books are the only closing figure, and there is no variance to show yet.

Refs: FR-11.2, D-281, D-284, D-285, D-287
"""

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, now_datetime

#: The stock a sale took, net of what its returns brought back.
SALES = {"Sales Invoice", "POS Invoice", "Delivery Note"}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.warehouse or not filters.opening_count:
		return _columns(), []

	start = _moment(filters.opening_count)
	end = _moment(filters.closing_count) if filters.closing_count else now_datetime()
	if end < start:
		frappe.throw(_("The closing count is before the opening count."))

	rows = _tally(filters, start, end)
	message = (
		None
		if filters.closing_count
		else _(
			"No closing count yet: the closing figures are the books', so there is no variance to show. "
			"Count the stock and choose that count as the closing one."
		)
	)
	return _columns(), rows, message


def _moment(count: str):
	posted = frappe.db.get_value(
		"Stock Reconciliation", count, ["posting_date", "posting_time", "docstatus"], as_dict=True
	)
	if not posted or posted.docstatus != 1:
		frappe.throw(_("{0} is not a submitted stock count.").format(count))
	return get_datetime(f"{posted.posting_date} {posted.posting_time}")


def _tally(filters, start, end) -> list[dict]:
	items = _stock_items(filters.item_group)
	if not items:
		return []

	fields = [
		"item_code",
		"voucher_type",
		"voucher_no",
		"actual_qty",
		"qty_after_transaction",
		"valuation_rate",
	]
	# **The period's movements only** — never the warehouse's whole history, which
	# grows by every sale for as long as the restaurant trades. The balance each
	# item opened at is read once per item below.
	entries = frappe.get_all(
		"Stock Ledger Entry",
		filters={
			"warehouse": filters.warehouse,
			"is_cancelled": 0,
			"item_code": ("in", list(items)),
			"posting_datetime": ("between", [start, end]),
		},
		fields=fields,
		order_by="posting_datetime asc, creation asc",
	)
	waste = _material_issues({e.voucher_no for e in entries if e.voucher_type == "Stock Entry"})

	held = set(
		frappe.get_all(
			"Bin",
			filters={"warehouse": filters.warehouse, "item_code": ("in", list(items))},
			pluck="item_code",
		)
	)
	rows: dict[str, dict] = {}
	for code in sorted(held | {entry.item_code for entry in entries}):
		opened = _opening(code, filters, start, fields)
		rows[code] = {
			"item_code": code,
			"item_name": items[code].item_name,
			"stock_uom": items[code].stock_uom,
			"opening": flt(opened.qty_after_transaction) if opened else 0.0,
			"received": 0.0,
			"sold": 0.0,
			"waste": 0.0,
			"other_out": 0.0,
			"closing": flt(opened.qty_after_transaction) if opened else 0.0,
			"rate": flt(opened.valuation_rate) if opened else 0.0,
		}

	for entry in entries:
		row = rows[entry.item_code]
		row["closing"] = flt(entry.qty_after_transaction)
		row["rate"] = flt(entry.valuation_rate) or row["rate"]
		if entry.voucher_no == filters.opening_count:
			row["opening"] = flt(entry.qty_after_transaction)
			continue

		qty = flt(entry.actual_qty)
		if entry.voucher_type == "Stock Reconciliation":
			# A count records the balance, not the change; the change is what the
			# balances leave unexplained, worked out below.
			continue
		if entry.voucher_type in SALES:
			row["sold"] -= qty
		elif entry.voucher_no in waste:
			row["waste"] -= qty
		elif qty > 0:
			row["received"] += qty
		else:
			row["other_out"] -= qty

	shown = []
	for row in rows.values():
		row["actual"] = row["opening"] + row["received"] - row["other_out"] - row["closing"]
		row["variance"] = row["actual"] - row["sold"] - row["waste"]
		row["variance_value"] = flt(row["variance"] * row["rate"], 2)
		row["variance_pct"] = flt(row["variance"] / row["sold"] * 100, 2) if row["sold"] else 0.0
		row["theoretical_value"] = flt(row["sold"] * row["rate"], 2)
		row["actual_value"] = flt(row["actual"] * row["rate"], 2)
		for field in ("opening", "received", "sold", "waste", "other_out", "closing", "actual", "variance"):
			row[field] = flt(row[field], 3)
		if any(row[field] for field in ("opening", "received", "sold", "waste", "closing")):
			shown.append(row)

	shown.sort(key=lambda row: abs(row["variance_value"]), reverse=True)
	return shown


def _opening(code: str, filters, start, fields: list[str]) -> frappe._dict | None:
	"""The item's last ledger entry before the period: what it opened at."""
	found = frappe.get_all(
		"Stock Ledger Entry",
		filters={
			"warehouse": filters.warehouse,
			"is_cancelled": 0,
			"item_code": code,
			"posting_datetime": ("<", start),
		},
		fields=fields,
		order_by="posting_datetime desc, creation desc",
		limit=1,
	)
	return found[0] if found else None


def _stock_items(item_group: str | None) -> dict[str, frappe._dict]:
	filters = {"is_stock_item": 1}
	if item_group:
		filters["item_group"] = item_group
	return {
		row.name: row
		for row in frappe.get_all("Item", filters=filters, fields=["name", "item_name", "stock_uom"])
	}


def _material_issues(entries: set[str]) -> set[str]:
	"""Stock written off on purpose — spoiled, dropped, given to staff."""
	if not entries:
		return set()
	return set(
		frappe.get_all(
			"Stock Entry",
			filters={"name": ("in", list(entries)), "purpose": "Material Issue", "docstatus": 1},
			pluck="name",
		)
	)


def _columns() -> list[dict]:
	def qty(fieldname, label, width=110):
		return {"fieldname": fieldname, "label": label, "fieldtype": "Float", "width": width}

	return [
		{
			"fieldname": "item_code",
			"label": _("Item", context="RPOS report"),
			"fieldtype": "Link",
			"options": "Item",
			"width": 220,
		},
		{
			"fieldname": "stock_uom",
			"label": _("Unit", context="RPOS report"),
			"fieldtype": "Data",
			"width": 70,
		},
		qty("opening", _("Opening Count", context="RPOS report")),
		qty("received", _("Received", context="RPOS report")),
		qty("sold", _("Theoretical (Sales)", context="RPOS report"), 130),
		qty("waste", _("Recorded Waste", context="RPOS report")),
		qty("other_out", _("Other Out", context="RPOS report")),
		qty("closing", _("Closing Count", context="RPOS report")),
		qty("actual", _("Actual Usage", context="RPOS report")),
		qty("variance", _("Variance", context="RPOS report")),
		# Float, not Percent: Frappe's total row averages a percent column.
		qty("variance_pct", _("Variance % of Theoretical", context="RPOS report"), 150),
		{
			"fieldname": "rate",
			"label": _("Unit Cost", context="RPOS report"),
			"fieldtype": "Currency",
			"width": 100,
		},
		{
			"fieldname": "theoretical_value",
			"label": _("Theoretical Cost", context="RPOS report"),
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"fieldname": "actual_value",
			"label": _("Actual Cost", context="RPOS report"),
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"fieldname": "variance_value",
			"label": _("Variance Cost", context="RPOS report"),
			"fieldtype": "Currency",
			"width": 120,
		},
	]

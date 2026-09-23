# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""When in the day the money comes in — the report a rota is written from.

A restaurant's day is not flat: a lunch hour can carry a third of the takings,
and knowing which hour that is decides how many people stand behind the counter.
Foodics and Toast both put this next to the product mix for that reason.

**The slot is the owner's to choose.** Sixty minutes is the honest default: a
restaurant's own rhythm is hourly, and a fifteen-minute row over a fortnight is
mostly noise. But a coffee bar with one rush lives inside a single hour, so half
and quarter hours are offered rather than argued about.

**Every slot in the day is listed, quiet ones included.** A gap is the answer to
"when is nobody here"; a report that draws only the busy rows makes the empty
afternoon invisible, which is the thing the rota needs to see (`D-074`).

**Refunds are not here.** A refund happens when the customer comes back, not
when the trade did, so putting it in an hour would say the wrong thing about
that hour. The day's report is where the money nets off.

Refs: FR-11.2, D-217, D-244
"""

import frappe
from frappe import _
from frappe.utils import flt, get_datetime

from restaurant_pos.utils import reporting

#: Minutes per row. An hour by default; the shorter ones are for one-rush shops.
SLOTS = (60, 30, 15)

MINUTES_IN_DAY = 24 * 60


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date, to_date = reporting.window(filters)
	slot = _slot(filters)

	orders = reporting.settled_orders(filters, from_date, to_date, ["sales_invoice", "closed_at"])
	money = _money_of([row.sales_invoice for row in orders])

	rows = {start: _slot_row(start, slot) for start in range(0, MINUTES_IN_DAY, slot)}
	for order in orders:
		taken = money.get(order.sales_invoice)
		if not taken:
			continue

		closed = get_datetime(order.closed_at)
		row = rows[(closed.hour * 60 + closed.minute) // slot * slot]
		row["bills"] += 1
		row["total"] += flt(taken.grand_total)

	listed = list(rows.values())
	takings = sum(row["total"] for row in listed)
	for row in listed:
		row["total"] = flt(row["total"], 2)
		row["average"] = flt(row["total"] / row["bills"], 2) if row["bills"] else 0.0
		row["share"] = flt(row["total"] / takings * 100, 2) if takings else 0.0

	return _columns(), ([*listed, _total(listed)] if takings else listed)


def _total(rows: list[dict]) -> dict:
	"""Its own, because Frappe's total row would add up the averages (`D-244`)."""
	bills = sum(row["bills"] for row in rows)
	total = flt(sum(row["total"] for row in rows), 2)

	return {
		"slot": _("Period Total"),
		"bills": bills,
		"total": total,
		"average": flt(total / bills, 2) if bills else 0.0,
		"share": flt(sum(row["share"] for row in rows), 2),
	}


def _slot(filters) -> int:
	minutes = int(filters.slot_minutes or SLOTS[0])
	if minutes not in SLOTS:
		frappe.throw(_("Choose a slot of {0} minutes.").format(", ".join(str(one) for one in SLOTS)))
	return minutes


def _slot_row(start: int, slot: int) -> dict:
	end = start + slot
	return {
		"slot": f"{start // 60:02d}:{start % 60:02d} - {end // 60 % 24:02d}:{end % 60:02d}",
		"bills": 0,
		"total": 0.0,
	}


def _money_of(invoices: list[str]) -> dict[str, frappe._dict]:
	if not invoices:
		return {}

	rows = frappe.get_all(
		"Sales Invoice",
		filters={"name": ("in", invoices), "docstatus": 1},
		fields=["name", "grand_total"],
	)
	return {row.name: row for row in rows}


def _columns() -> list[dict]:
	return [
		{"fieldname": "slot", "label": _("Time Slot"), "fieldtype": "Data", "width": 140},
		{"fieldname": "bills", "label": _("Bills"), "fieldtype": "Int", "width": 100},
		{"fieldname": "total", "label": _("Total Taken"), "fieldtype": "Currency", "width": 160},
		{"fieldname": "average", "label": _("Average Bill"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "share", "label": _("Share of Sales %"), "fieldtype": "Float", "width": 140},
	]

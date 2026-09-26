# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Hours each person worked, and what was sold an hour (`D-274`).

The roster says who is on the clock now; this says the month. **What a labour
report can be without payroll** — the cost of an hour is a salary this system
does not hold (`D-247`), but the hours are the punches it does, and sales per
hour worked is the figure a rota is judged by.

**Hours come from the roster's own arithmetic** (`attendance._worked`), not a
second count: each `IN` to the `OUT` after it, and a shift still open counts to
the end of the period, or to now if that is sooner. **Sales are the bills the
person took the money for** (`cashier`, as `Staff Sales` reads them), matched
through the employee's user.

Refs: FR-8.4, FR-11.2, D-247, D-274
"""

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, now_datetime

from restaurant_pos.utils import attendance, reporting


def execute(filters=None):
	filters = frappe._dict(filters or {})
	filters.pop("order_type", None)
	from_date, to_date = reporting.window(filters)

	if not attendance.is_available():
		return _columns(), []

	employees = attendance.staff_of(filters.branch)
	if not employees:
		return _columns(), []

	punches = frappe.get_all(
		attendance.CHECKIN,
		filters={
			"employee": ("in", [row.name for row in employees]),
			"time": ("between", [from_date, to_date]),
		},
		fields=["employee", "log_type", "time"],
		order_by="employee asc, time asc",
		limit_page_length=0,
	)
	until = min(get_datetime(to_date), now_datetime())
	by_employee = {row.name: row for row in employees}
	worked = {
		name: attendance._worked(by_employee[name], rows, until=until)["minutes"]
		for name, rows in attendance._by_employee(punches).items()
	}

	users = (
		dict(
			frappe.get_all(
				"Employee", filters={"name": ("in", list(worked))}, fields=["name", "user_id"], as_list=True
			)
		)
		if worked
		else {}
	)
	sold: dict[str, float] = {}
	for order in reporting.settled_orders(filters, from_date, to_date, ["cashier", "total_amount"]):
		sold[order.cashier] = sold.get(order.cashier, 0.0) + flt(order.total_amount)

	rows = []
	for name, minutes in worked.items():
		hours = flt(minutes / 60, 2)
		sales = flt(sold.get(users.get(name), 0.0), 2)
		rows.append(
			{
				"employee": name,
				"employee_name": by_employee[name].employee_name,
				"hours": hours,
				"sales": sales,
				"per_hour": flt(sales / hours, 2) if hours else 0.0,
			}
		)

	rows.sort(key=lambda row: -row["hours"])
	total_hours = flt(sum(row["hours"] for row in rows), 2)
	total_sales = flt(sum(row["sales"] for row in rows), 2)
	total = {
		"employee_name": _("Total"),
		"hours": total_hours,
		"sales": total_sales,
		"per_hour": flt(total_sales / total_hours, 2) if total_hours else 0.0,
	}
	return _columns(), ([*rows, total] if rows else rows)


def _columns() -> list[dict]:
	return [
		{
			"fieldname": "employee",
			"label": _("Employee"),
			"fieldtype": "Link",
			"options": "Employee",
			"width": 130,
		},
		{"fieldname": "employee_name", "label": _("Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "hours", "label": _("Hours"), "fieldtype": "Float", "width": 90},
		{"fieldname": "sales", "label": _("Sales Taken"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "per_hour", "label": _("Sales an Hour"), "fieldtype": "Currency", "width": 120},
	]

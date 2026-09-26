# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The five reports that finish the list the user asked for (`D-274`).

Each holds the one claim its figure rests on: a table's guests and minutes, an
extra counted by the line's quantity at the price it was rung at, the walk-in
kept off the customer list, an offer's give-away read from the bill, and hours
taken from the roster's own arithmetic.

**Measured as differences** where the test site's other bills would otherwise be
counted too.

Refs: FR-11.2, D-274
"""

import json

import frappe
from frappe.utils import add_to_date, flt, get_datetime, today

from restaurant_pos.restaurant_pos.report.customer_sales import customer_sales
from restaurant_pos.restaurant_pos.report.guests_and_tables import guests_and_tables
from restaurant_pos.restaurant_pos.report.hours_worked import hours_worked
from restaurant_pos.restaurant_pos.report.modifier_sales import modifier_sales
from restaurant_pos.restaurant_pos.report.promotion_sales import promotion_sales
from restaurant_pos.tests.test_auth import _employee_for
from restaurant_pos.tests.test_gift_card import _a_customer
from restaurant_pos.tests.test_payment import PaymentTestBase
from restaurant_pos.tests.test_permissions import _make_user

PERIOD = {"from_date": today(), "to_date": today()}


def _row(report, key: str, value, **filters) -> dict:
	_columns, rows = report.execute({**PERIOD, **filters})
	return next((row for row in rows if row.get(key) == value), {})


class TestTheRestOfTheList(PaymentTestBase):
	def _sold(self, qty: float = 2):
		order = self._payable_order(qty=qty)
		self._pay(order)
		order.reload()
		return order

	def test_a_table_counts_its_turn_its_guests_and_its_minutes(self):
		table = frappe.db.get_value("Restaurant Table", {}, "name")
		before = _row(guests_and_tables, "table", table)
		order = self._sold()
		frappe.db.set_value(
			"Restaurant Order",
			order.name,
			{"table": table, "cover_count": 3, "opened_at": add_to_date(order.closed_at, minutes=-45)},
		)

		after = _row(guests_and_tables, "table", table)
		self.assertEqual(after["turns"] - before.get("turns", 0), 1)
		self.assertEqual(after["guests"] - before.get("guests", 0), 3)
		self.assertGreater(after["average_minutes"], 0)

	def test_an_extra_counts_by_the_line_s_quantity_at_its_rung_price(self):
		order = self._sold(qty=3)
		line = order.items[0]
		frappe.db.set_value(
			"Restaurant Order Item",
			line.name,
			"modifiers",
			json.dumps(
				[
					{
						"group": "RPOS Report Extras",
						"option": "RPOS Cheese",
						"option_ar": "جبن",
						"price_effect": "add",
						"amount": 4,
					}
				]
			),
		)

		row = _row(modifier_sales, "group", "RPOS Report Extras")
		self.assertEqual(row["times"], flt(line.qty))
		self.assertAlmostEqual(row["revenue"], 4 * flt(line.qty), places=2)

	def test_a_named_customer_is_listed_and_the_walk_in_is_not(self):
		customer = _a_customer()
		before = _row(customer_sales, "customer", customer)
		order = self._sold()
		frappe.db.set_value("Restaurant Order", order.name, "customer", customer)

		after = _row(customer_sales, "customer", customer)
		self.assertEqual(after["bills"] - before.get("bills", 0), 1)

		walk_in = frappe.db.get_value("POS Profile", self.profile, "customer")
		if walk_in:
			self.assertFalse(_row(customer_sales, "customer", walk_in))

	def test_an_offer_s_give_away_is_read_from_the_bill(self):
		offer = frappe.get_doc(
			{
				"doctype": "Restaurant Promotion",
				"title": "RPOS report offer",
				"title_ar": "عرض التقرير",
				"is_active": 0,
				"promotion_type": "percentage",
				"discount_value": 10,
				"apply_to": "all",
				"item_scope": "all",
			}
		).insert(ignore_permissions=True)
		order = self._sold()
		frappe.db.set_value("Restaurant Order", order.name, {"promotion": offer.name, "promotion_amount": 5})

		row = _row(promotion_sales, "promotion", offer.name)
		self.assertEqual(row["bills"], 1)
		self.assertAlmostEqual(row["given"], 5, places=2)

	def test_hours_come_from_the_punches(self):
		user = _make_user("rpos_hours_report@example.com", "POS Cashier")
		employee = _employee_for(user)
		if not employee:
			self.skipTest("this site cannot make an Employee")
		start = get_datetime(f"{today()} 09:00:00")
		for log_type, at in (("IN", start), ("OUT", add_to_date(start, hours=2))):
			frappe.get_doc(
				{"doctype": "Employee Checkin", "employee": employee, "log_type": log_type, "time": at}
			).insert(ignore_permissions=True)

		row = _row(hours_worked, "employee", employee)
		self.assertAlmostEqual(row["hours"], 2, places=2)

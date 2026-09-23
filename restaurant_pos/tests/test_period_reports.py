# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The two reports that read a period rather than a day (`D-244`).

`Daily Sales` is what an owner compares one week with the last on, and
`Hourly Sales` is what a rota is written from, so the claims tested are the ones
those two decisions rest on: a settled bill lands on its own day and in its own
slot, the average bill is takings over bills and never a mean of means, a refund
comes off the day it was paid out, and a quiet hour is listed as quiet rather
than left off the page.

**Measured as differences, not totals** — the suite's own bills pile up on the
test site, so an absolute figure would assert the database, not the report.

Refs: FR-11.2, D-217, D-244
"""

import frappe
from frappe.utils import add_days, flt, get_datetime, now_datetime, today

from restaurant_pos.restaurant_pos.report.daily_sales import daily_sales as daily
from restaurant_pos.restaurant_pos.report.hourly_sales import hourly_sales as hourly
from restaurant_pos.tests.test_payment import PaymentTestBase
from restaurant_pos.utils import returns

REASON = "goods_returned"


def _today_row(**filters) -> dict:
	filters = {"from_date": today(), "to_date": today(), **filters}
	_columns, rows = daily.execute(filters)
	for row in rows:
		if row["day"] == today():
			return row
	return {"bills": 0, "total": 0.0, "returns": 0.0, "net": 0.0, "sales": 0.0}


def _slot_row(**filters) -> dict:
	"""The slot the clock is in right now — where a bill settled now will land."""
	filters = {"from_date": today(), "to_date": today(), **filters}
	slot = int(filters.get("slot_minutes") or 60)
	_columns, rows = hourly.execute(filters)

	now = now_datetime()
	start = (now.hour * 60 + now.minute) // slot * slot
	label = f"{start // 60:02d}:{start % 60:02d}"
	return next(row for row in rows if row["slot"].startswith(label))


class TestTheDay(PaymentTestBase):
	def test_a_settled_bill_lands_on_the_day_it_was_settled(self):
		before = _today_row()

		order = self._payable_order(qty=2)
		self._pay(order)

		after = _today_row()
		self.assertEqual(after["bills"] - before["bills"], 1)
		self.assertGreater(after["total"], before["total"])

	def test_the_takings_carry_their_vat_and_the_sales_line_does_not(self):
		before = _today_row()

		order = self._payable_order(qty=1)
		self._pay(order)

		invoice = frappe.get_doc("Sales Invoice", order.sales_invoice)
		after = _today_row()
		self.assertAlmostEqual(after["total"] - before["total"], flt(invoice.grand_total), places=2)
		self.assertAlmostEqual(after["sales"] - before["sales"], flt(invoice.net_total), places=2)

	def test_a_refund_comes_off_the_day_it_was_paid_out(self):
		order = self._payable_order(qty=2)
		self._pay(order)
		before = _today_row()

		line = returns.returnable(order)["items"][0]["row"]
		returns.create_return(order, items=[{"row": line, "qty": 1}], reason_code=REASON)

		after = _today_row()
		self.assertGreater(after["returns"], before["returns"])
		self.assertLess(after["net"] - before["net"], 0)

	def test_the_last_line_averages_the_period_and_does_not_add_up_averages(self):
		order = self._payable_order(qty=1)
		self._pay(order)

		_columns, rows = daily.execute({"from_date": add_days(today(), -30), "to_date": today()})
		total = rows[-1]
		days = rows[:-1]

		self.assertIsNone(total["day"], "the last line is the period's, not a day's")
		self.assertAlmostEqual(total["average"], total["total"] / total["bills"], places=2)
		if len(days) > 1:
			self.assertNotAlmostEqual(total["average"], sum(day["average"] for day in days), places=2)

	def test_another_branch_s_days_stay_out(self):
		order = self._payable_order(qty=1)
		self._pay(order)

		self.assertEqual(_today_row(branch="RPOS No Such Branch")["bills"], 0)


class TestTheHour(PaymentTestBase):
	def test_a_bill_lands_in_the_slot_it_was_settled_in(self):
		before = _slot_row()

		order = self._payable_order(qty=1)
		self._pay(order)

		self.assertEqual(_slot_row()["bills"] - before["bills"], 1)

	def test_every_slot_of_the_day_is_listed_even_the_quiet_ones(self):
		"""`D-074` — a gap is the answer to "when is nobody here"."""
		for minutes, expected in ((60, 24), (30, 48), (15, 96)):
			with self.subTest(slot=minutes):
				_columns, rows = hourly.execute(
					{"from_date": today(), "to_date": today(), "slot_minutes": minutes}
				)
				self.assertGreaterEqual(len(rows), expected)

	def test_a_finer_slot_splits_an_hour_without_losing_a_bill(self):
		order = self._payable_order(qty=1)
		self._pay(order)
		closed = get_datetime(frappe.db.get_value("Restaurant Order", order.name, "closed_at"))
		label = f"{closed.hour:02d}:"

		def that_hour(minutes: int) -> tuple[int, float]:
			"""How many rows cover that hour, and how many bills they hold."""
			_columns, rows = hourly.execute(
				{"from_date": today(), "to_date": today(), "slot_minutes": minutes}
			)
			slots = [row for row in rows[:-1] if row["slot"].startswith(label)]
			return len(slots), sum(row["bills"] for row in slots)

		whole, hour_bills = that_hour(60)
		quarters, quarter_bills = that_hour(15)

		self.assertEqual((whole, quarters), (1, 4))
		self.assertEqual(quarter_bills, hour_bills)

	def test_a_slot_nobody_offers_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			hourly.execute({"from_date": today(), "to_date": today(), "slot_minutes": 7})

	def test_the_shares_add_up_to_the_whole_day(self):
		order = self._payable_order(qty=1)
		self._pay(order)

		_columns, rows = hourly.execute({"from_date": today(), "to_date": today()})

		self.assertAlmostEqual(rows[-1]["share"], 100.0, places=1)

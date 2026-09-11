# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The balance report: what the restaurant owes in points on a chosen day (`D-196`).

The accountant books a month-end entry from this figure (`docs/12` §5.3), so the
claims are the ones that entry rests on: the day is the day asked for, not today;
a point counts through its last day and not after; the value is net of the VAT
the menu includes, read from the terminal's template; a customer's debt is kept
out of what the restaurant owes; and the share expected to be spent is the
accountant's to set.

Refs: BR-080, D-189, D-196
"""

import frappe
from frappe.utils import add_days, cint, today

from restaurant_pos.restaurant_pos.report.loyalty_points_balance import loyalty_points_balance as report
from restaurant_pos.tests.test_loyalty import LEDGER, POINT_VALUE, LoyaltyTestBase
from restaurant_pos.utils import loyalty

#: The test terminal's template, from the demo builder (`LoyaltyTestBase`).
VAT = 1.15


def _liability(share: int) -> str:
	return f"Liability at {share}% expected to be spent"


class TestBalanceReport(LoyaltyTestBase):
	def _row(self, customer: str, points: int, *, posted: int = 0, expires: int = 365, against=None) -> str:
		"""A ledger row posted and expiring the given number of days from today.

		A movement passes its grant's expiry, as the ledger's one rule requires.
		"""
		return (
			frappe.get_doc(
				{
					"doctype": LEDGER,
					"company": self.company,
					"loyalty_program": self.program,
					"customer": customer,
					"loyalty_points": points,
					"purchase_amount": 0,
					"redeem_against": against,
					"posting_date": add_days(today(), posted),
					"expiry_date": add_days(today(), expires),
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _held(self, customer: str, day: int) -> int:
		rows = loyalty.balances(add_days(today(), day), customer=customer)
		return cint(rows[0].points) if rows else 0

	def _run(self, **filters):
		_columns, data, message, _chart, summary = report.execute({"company": self.company, **filters})
		return data, message, {item["label"]: item["value"] for item in summary}

	def test_a_past_day_reads_what_stood_that_night(self):
		"""Spending after the month closed does not change the month's figure."""
		guest = self._guest()
		grant = self._row(guest, 300, posted=-10)
		self._row(guest, -100, posted=-2, against=grant)

		self.assertEqual(self._held(guest, -11), 0, "nothing was earned yet")
		self.assertEqual(self._held(guest, -5), 300, "the spending came after")
		self.assertEqual(self._held(guest, 0), 200)
		self.assertEqual(self._balance(guest), 200, "the till reads the same sum")

	def test_a_point_counts_through_its_last_day_and_not_after(self):
		guest = self._guest()
		self._row(guest, 120, expires=5)

		self.assertEqual(self._held(guest, 5), 120)
		self.assertEqual(self._held(guest, 6), 0)

	def test_the_value_is_net_of_the_vat_the_menu_includes(self):
		"""460 points at 0.05 are 23 riyals: 20 of revenue and 3 of VAT (`docs/12` §5)."""
		guest = self._guest()
		self._row(guest, 460)

		data, message, _summary = self._run(customer=guest)

		self.assertEqual(
			[(row["customer"], row["points"], row["value"], row["net"]) for row in data],
			[(guest, 460, 460 * POINT_VALUE, 20.0)],
		)
		self.assertIn("15%", message)

	def test_a_customers_debt_is_listed_and_kept_out_of_what_is_owed(self):
		"""A clawback after spending leaves a customer below zero (`D-189`)."""
		_data, _message, before = self._run()
		keeps, owes = self._guest(), self._guest()
		self._row(keeps, 400)
		grant = self._row(owes, 100)
		self._row(owes, -100, against=grant)  # spent
		self._row(owes, -100, against=grant)  # then clawed back by a return

		data, _message, after = self._run()

		self.assertIn((owes, -100), [(row["customer"], row["points"]) for row in data])
		self.assertEqual(after["Points held"] - before["Points held"], 400)
		self.assertEqual(
			after["Points owed back by customers"] - before.get("Points owed back by customers", 0), 100
		)
		# Each total is rounded once, so the difference of two may be a cent off.
		self.assertAlmostEqual(
			after[_liability(100)] - before[_liability(100)], 400 * POINT_VALUE / VAT, delta=0.011
		)

	def test_the_share_expected_to_be_spent_is_the_accountants(self):
		guest = self._guest()
		self._row(guest, 460)

		_data, _message, summary = self._run(customer=guest, expected_redemption=80)

		self.assertEqual(summary["Net of VAT"], 20.0)
		self.assertEqual(summary[_liability(80)], 16.0)

	def test_terminals_that_disagree_on_vat_leave_the_net_to_the_accountant(self):
		"""Rather than pick one rate and hand over a wrong liability."""
		guest = self._guest()
		self._row(guest, 460)
		self._terminal_at(5)

		data, message, summary = self._run(customer=guest)

		self.assertIsNone(data[0]["net"])
		self.assertNotIn("Net of VAT", summary)
		self.assertIn("disagree", message)

	def test_a_terminal_with_no_template_says_nothing_about_the_rate(self):
		"""The work site has one beside its 15% terminal; it must not blank the net."""
		guest = self._guest()
		self._row(guest, 460)
		self._terminal_at(None)

		data, _message, _summary = self._run(customer=guest)

		self.assertEqual(data[0]["net"], 20.0)

	def test_with_prices_before_vat_the_points_are_revenue_whole(self):
		"""Points come off before the tax (`FR-10.4`), so none of their value is VAT."""
		guest = self._guest()
		self._row(guest, 460)
		template = frappe.db.get_value("POS Profile", self.profile, "taxes_and_charges")
		frappe.db.set_value("Sales Taxes and Charges", {"parent": template}, "included_in_print_rate", 0)
		self.addCleanup(
			frappe.db.set_value, "Sales Taxes and Charges", {"parent": template}, "included_in_print_rate", 1
		)

		data, message, _summary = self._run(customer=guest)

		self.assertEqual(data[0]["net"], 460 * POINT_VALUE)
		self.assertIn("before VAT", message)

	def _terminal_at(self, rate: float | None) -> str:
		"""A second terminal of the same company, under another VAT rate — or none.

		Removed when the test ends. The class shares its rows, and left behind it
		made every later test in the class read two disagreeing terminals.
		"""
		template = None
		if rate is not None:
			ours = frappe.db.get_value("POS Profile", self.profile, "taxes_and_charges")
			copy = frappe.copy_doc(frappe.get_doc("Sales Taxes and Charges Template", ours))
			copy.title = f"RPOS Test VAT {rate:g}"
			copy.is_default = 0
			for row in copy.taxes:
				row.rate = rate
			template = copy.insert(ignore_permissions=True).name
			self.addCleanup(frappe.delete_doc, copy.doctype, template, force=1, ignore_permissions=True)

		terminal = frappe.copy_doc(frappe.get_doc("POS Profile", self.profile))
		terminal.taxes_and_charges = template
		terminal.applicable_for_users = []
		label = "no VAT" if rate is None else f"{rate:g}"
		terminal.insert(ignore_permissions=True, set_name=f"RPOS Test Terminal {label}")
		# Registered last so it runs first: the terminal names the template.
		self.addCleanup(frappe.delete_doc, terminal.doctype, terminal.name, force=1, ignore_permissions=True)
		return terminal.name

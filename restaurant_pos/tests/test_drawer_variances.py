# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The drawers that did not count out, and who closed them (`D-273`).

What an owner reads when money feels short: a short drawer is on the page with
the reason its cashier gave, a balanced one stays off it unless asked for, and
the view by cashier keeps shortages and overages apart — a net of zero can hide
a big short and a big over on the same person.

Refs: FR-8.3, BR-043, D-273
"""

from unittest.mock import patch

import frappe
from frappe.utils import today

from restaurant_pos.restaurant_pos.report.drawer_variances import drawer_variances as report
from restaurant_pos.tests.test_payment import CASH
from restaurant_pos.tests.test_shift import ShiftTestBase
from restaurant_pos.utils import shift as service


class TestTheDrawers(ShiftTestBase):
	def _closed(self, off_by: float, reason: str | None = None) -> str:
		entry = service.open_till(pos_profile=self.profile, opening_floats={CASH: 100})["entry"]
		expected = service.summarise_till(entry)["till_expected"]
		read_profile = service._profile

		def counting(pos_profile):
			profile = read_profile(pos_profile)
			profile.settlement_required = 1
			return profile

		with patch.object(service, "_profile", side_effect=counting):
			service.close_till(opening_entry=entry, counted={CASH: expected + off_by}, variance_reason=reason)
		return frappe.db.get_value("POS Closing Entry", {"pos_opening_entry": entry, "docstatus": 1}, "name")

	def _rows(self, **filters) -> list[dict]:
		_columns, rows = report.execute({"from_date": today(), "to_date": today(), **filters})
		return rows

	def test_a_short_drawer_is_listed_with_its_reason(self):
		closing = self._closed(-7, reason="RPOS short by seven")

		row = next(row for row in self._rows(only_differences=1) if row.get("closing") == closing)
		self.assertAlmostEqual(row["difference"], -7, places=2)
		self.assertEqual(row["reason"], "RPOS short by seven")
		self.assertEqual(row["cashier"], frappe.session.user)

	def test_a_balanced_drawer_is_left_off_unless_asked_for(self):
		closing = self._closed(0)

		self.assertNotIn(closing, [row.get("closing") for row in self._rows(only_differences=1)])
		self.assertIn(closing, [row.get("closing") for row in self._rows(only_differences=0)])

	def test_by_cashier_keeps_shortages_and_overages_apart(self):
		before = next(
			(row for row in self._rows(by_cashier=1) if row["cashier"] == frappe.session.user),
			{"drawers": 0, "short_drawers": 0, "short": 0.0, "over": 0.0},
		)
		self._closed(-10, reason="RPOS short")
		self._closed(10, reason="RPOS over")

		after = next(row for row in self._rows(by_cashier=1) if row["cashier"] == frappe.session.user)
		self.assertEqual(after["drawers"] - before["drawers"], 2)
		self.assertEqual(after["short_drawers"] - before["short_drawers"], 1)
		self.assertAlmostEqual(after["short"] - before["short"], -10, places=2)
		self.assertAlmostEqual(after["over"] - before["over"], 10, places=2)

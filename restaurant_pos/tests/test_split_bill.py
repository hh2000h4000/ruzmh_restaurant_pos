# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Splitting a bill evenly between the people at the table.

The whole difficulty is the last five halalas. 100.00 between three is 33.3333,
and rounding each share to the 0.05 a riyal is settled in gives 33.35 three
times — 100.05, which the restaurant would have charged and cannot bank.
Rounding down loses money the other way, on every split bill, forever.

So the arithmetic runs in whole rounding steps and the sum is exact by
construction. These tests check that construction rather than a handful of
convenient numbers: the sum property is asserted across every total and every
party size a restaurant plausibly sees, because the case that breaks is the one
nobody thought to write down.

Refs: BR-024, FR-10.1
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant_pos.utils import totals

STEP = 0.05


class SplittingEvenly(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# The step ships as 0 for SAR and `setup/defaults.py` sets it; a site
		# that has not been set up would otherwise test whole-riyal rounding.
		frappe.db.set_value("Currency", "SAR", "smallest_currency_fraction_value", STEP)
		frappe.db.commit()

	# ------------------------------------------------------------------ #

	def test_the_shares_add_back_up_to_the_bill(self):
		"""The property everything else rests on.

		Swept rather than sampled: every 0.05 from nothing to 300 riyals, split
		between one and twelve people. If a rounding rule can lose a halala,
		it loses it somewhere in here.
		"""
		for units in range(0, 6001):
			total = round(units * STEP, 2)
			for ways in range(1, 13):
				shares = totals.split_evenly(total, ways)
				self.assertAlmostEqual(
					sum(shares),
					total,
					places=2,
					msg=f"{total} between {ways} came to {sum(shares)}",
				)

	def test_every_share_is_payable_in_cash(self):
		"""A share of 33.333 cannot be handed over in riyals and halalas."""
		for total in (100.00, 87.35, 12.05, 250.00):
			for ways in range(1, 8):
				for share in totals.split_evenly(total, ways):
					self.assertAlmostEqual(
						share / STEP,
						round(share / STEP),
						places=6,
						msg=f"{share} is not a multiple of {STEP}",
					)

	def test_no_two_people_pay_more_than_a_step_apart(self):
		"""Even means even: the odd halalas cannot pile onto one person."""
		for total in (100.00, 87.35, 0.15, 1000.00):
			for ways in range(1, 10):
				shares = totals.split_evenly(total, ways)
				self.assertLessEqual(
					max(shares) - min(shares),
					STEP + 1e-9,
					msg=f"{total} between {ways} gave {shares}",
				)

	def test_nobody_is_asked_for_a_negative_amount(self):
		"""A bill too small to go round. Four people, ten halalas: two of them
		pay nothing, and that is arithmetic, not a bug. The version that
		rounded each share first handed the last person -0.05."""
		shares = totals.split_evenly(0.10, 4)
		self.assertEqual(shares, [0.05, 0.05, 0.0, 0.0])

	def test_the_classic_case(self):
		self.assertEqual(totals.split_evenly(100.00, 3), [33.35, 33.35, 33.30])

	def test_one_person_pays_the_bill(self):
		self.assertEqual(totals.split_evenly(87.35, 1), [87.35])

	def test_a_bill_cannot_be_split_between_nobody(self):
		for ways in (0, -1, None):
			with self.assertRaises(frappe.ValidationError):
				totals.split_evenly(100.00, ways)

	def test_the_earlier_payers_carry_the_odd_halalas(self):
		"""Somebody has to. It is the person standing at the till first, and it
		is decided here rather than left to whichever way the float fell."""
		shares = totals.split_evenly(10.00, 3)
		self.assertEqual(shares, [3.35, 3.35, 3.30])
		self.assertGreaterEqual(shares[0], shares[-1])

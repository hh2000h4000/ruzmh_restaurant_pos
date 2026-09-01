# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The arithmetic contract the device is held to (D-071).

`shared/totals_contract.json` carries the server's own answers so the offline
port can be checked against them. **This is the other half of that check**: if
`utils/totals` changes and the file is not regenerated, this fails — so the
contract cannot quietly stop describing the server it claims to describe.

Between them, the two tests turn "the device agrees with the backend" from a
hope into something that breaks a build.

Refs: D-071, CLAUDE.md §5.1, 09 §5
"""

import json
from pathlib import Path

from frappe.tests.utils import FrappeTestCase

from restaurant_pos.utils import totals

CONTRACT = Path(__file__).resolve().parents[2] / "shared" / "totals_contract.json"


class TestTheTotalsContract(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.contract = json.loads(CONTRACT.read_text())

	def test_the_file_is_there_and_exercises_tax(self):
		"""A contract that never taxes anything would pass while proving nothing."""
		profiles = self.contract["profiles"]
		self.assertGreater(len(profiles), 1)
		self.assertTrue(any(profile["pricing"]["tax_rate"] > 0 for profile in profiles))

	def test_it_exercises_tax_both_ways_round(self):
		"""Extracting tax from a price is different arithmetic from adding it.

		A contract that only ever added it would let the inclusive path — the
		one a Saudi menu actually uses (`D-091`) — drift on the device with
		nothing to catch it.
		"""
		taxed = [p for p in self.contract["profiles"] if p["pricing"]["tax_rate"] > 0]

		self.assertTrue(any(p["pricing"].get("tax_inclusive") for p in taxed))
		self.assertTrue(any(not p["pricing"].get("tax_inclusive") for p in taxed))

	def test_the_two_modes_do_not_agree(self):
		"""If they produced the same numbers, one of them would be wrong.

		The guard is against a `tax_inclusive` flag that is carried everywhere
		and read nowhere — which would pass every other test in this file.
		"""
		by_mode = {}
		for profile in self.contract["profiles"]:
			if profile["pricing"]["tax_rate"] > 0:
				by_mode[bool(profile["pricing"].get("tax_inclusive"))] = profile

		inclusive = by_mode[True]["cases"]
		exclusive = by_mode[False]["cases"]
		differing = [
			one["name"]
			for one, other in zip(inclusive, exclusive, strict=True)
			if one["expect"]["total_amount"] != other["expect"]["total_amount"]
		]

		self.assertTrue(differing, "the inclusive flag changed nothing")

	def test_the_server_still_answers_what_the_contract_says(self):
		for profile in self.contract["profiles"]:
			pricing = profile["pricing"]
			for case in profile["cases"]:
				with self.subTest(tax=pricing["tax_rate"], case=case["name"]):
					self.assertEqual(
						totals.compute(
							case["lines"],
							case["discount_type"],
							case["discount_value"],
							pricing,
						),
						case["expect"],
					)

	def test_the_terminal_ships_the_inputs_a_device_needs(self):
		"""Every one of these is a server setting the device must not guess."""
		pricing = totals.pricing_inputs("RPOS Test Terminal")

		for key in (
			"currency",
			"precision",
			"tax_rate",
			"tax_inclusive",
			"rounding_step",
			"rounding_method",
		):
			self.assertIn(key, pricing)

		# BR-024, and the trap `utils/totals.round_to_step` documents: SAR ships
		# with this field at zero, which rounds every bill to whole riyals.
		self.assertEqual(pricing["rounding_step"], 0.05)

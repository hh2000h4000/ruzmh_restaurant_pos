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

		for key in ("currency", "precision", "tax_rate", "rounding_step", "rounding_method"):
			self.assertIn(key, pricing)

		# BR-024, and the trap `utils/totals.round_to_step` documents: SAR ships
		# with this field at zero, which rounds every bill to whole riyals.
		self.assertEqual(pricing["rounding_step"], 0.05)

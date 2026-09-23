# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""What a modifier option does to a line's price.

`replace` was retired here (`D-241`): it read as "this becomes the price" and
was coded as an addition on both sides of the wire, so a manager pricing a large
drink at 18 got 12 + 18 on the bill. The three effects that remain each do what
their name says, and this module holds them to it.

Refs: FR-4.2, D-241
"""

import frappe

from restaurant_pos.patches.v1_0.retire_replace_price_effect import execute as retire_replace
from restaurant_pos.tests.test_order import ITEM, OrderTestBase
from restaurant_pos.utils import order as service

GROUP = "RPOS Test Size"


def _group(*options) -> str:
	"""A modifier group carrying ``options`` as ``(title, effect, amount)``."""
	if frappe.db.exists("POS Modifier Group", GROUP):
		frappe.delete_doc("POS Modifier Group", GROUP, force=True, ignore_permissions=True)

	frappe.get_doc(
		{
			"doctype": "POS Modifier Group",
			"__newname": GROUP,
			"title": GROUP,
			"title_ar": "الحجم",
			"selection_type": "single",
			"is_required": 0,
			"modifier_options": [
				{
					"title": title,
					"title_ar": title,
					"price_effect": effect,
					"price_amount": amount,
					"is_active": 1,
				}
				for title, effect, amount in options
			],
		}
	).insert(ignore_permissions=True)

	return GROUP


class TestThePriceEffects(OrderTestBase):
	def test_each_effect_moves_the_line_the_way_its_name_says(self):
		_group(("Plain", "none", 0), ("Large", "add", 6), ("Kids", "subtract", 5))
		order = self._order()

		for option, expected in (("Plain", 25.0), ("Large", 31.0), ("Kids", 20.0)):
			with self.subTest(option=option):
				resolved, delta = service._resolve_modifiers(ITEM, [{"group": GROUP, "option": option}])
				self.assertEqual(len(resolved), 1)
				self.assertEqual(25.0 + delta, expected)

		self.assertTrue(order.name)

	def test_replace_is_no_longer_on_offer(self):
		"""The trap is gone from the form, not merely discouraged in the guide."""
		options = frappe.get_meta("POS Modifier Option").get_field("price_effect").options
		self.assertEqual(options.split("\n"), ["none", "add", "subtract"])


class TestRetiringReplace(OrderTestBase):
	def test_a_row_left_holding_replace_becomes_the_add_it_always_was(self):
		"""No bill changes amount: `replace` had been adding all along (D-076)."""
		_group(("Large", "add", 18))
		frappe.db.set_value(
			"POS Modifier Option",
			{"parent": GROUP, "title": "Large"},
			"price_effect",
			"replace",
			update_modified=False,
		)

		retire_replace()

		self.assertEqual(
			frappe.db.get_value("POS Modifier Option", {"parent": GROUP, "title": "Large"}, "price_effect"),
			"add",
		)

	def test_it_says_nothing_and_does_nothing_on_a_clean_site(self):
		_group(("Large", "add", 18))

		retire_replace()

		self.assertEqual(
			frappe.db.count("POS Modifier Option", {"price_effect": "replace"}),
			0,
		)

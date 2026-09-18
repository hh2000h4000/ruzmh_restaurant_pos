# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""An order type may sell from its own price list.

A delivery platform takes a commission, so its menu is priced above the dining
room's. Getting this wrong sells at the wrong price all day without an error.

Refs: FR-1.6, D-036
"""

import frappe

from restaurant_pos.api import session
from restaurant_pos.setup import test_fixtures
from restaurant_pos.tests.test_order import ITEM, OrderTestBase
from restaurant_pos.utils import order as service

DELIVERY_LIST = "RPOS Test Delivery"
DELIVERY_RATE = 40.0


class TestOrderTypePricing(OrderTestBase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		if not frappe.db.exists("Price List", DELIVERY_LIST):
			frappe.get_doc(
				{
					"doctype": "Price List",
					"price_list_name": DELIVERY_LIST,
					"currency": "SAR",
					"selling": 1,
					"enabled": 1,
				}
			).insert(ignore_permissions=True)

		if not frappe.db.exists("Item Price", {"item_code": ITEM, "price_list": DELIVERY_LIST}):
			frappe.get_doc(
				{
					"doctype": "Item Price",
					"item_code": ITEM,
					"price_list": DELIVERY_LIST,
					"selling": 1,
					"price_list_rate": DELIVERY_RATE,
				}
			).insert(ignore_permissions=True)

		frappe.db.commit()

	def setUp(self):
		frappe.db.set_value("Restaurant Order Type", self.order_type, "selling_price_list", DELIVERY_LIST)
		frappe.clear_cache(doctype="Restaurant Order Type")

	def tearDown(self):
		frappe.db.set_value("Restaurant Order Type", self.order_type, "selling_price_list", None)
		frappe.clear_cache(doctype="Restaurant Order Type")

	def test_the_order_type_price_wins_over_the_terminal(self):
		order = self._order(order_type=self.order_type)
		service.add_item(order, item=ITEM, qty=1)

		self.assertEqual(order.items[0].rate, DELIVERY_RATE)

	def test_a_type_with_no_list_of_its_own_uses_the_terminal(self):
		table = frappe.db.get_value("Restaurant Table", {"section": self.section, "is_active": 1}, "name")
		frappe.db.set_value("Restaurant Table", table, {"status": "available", "current_order": None})

		order = self._order(order_type=self.dine_in, table=table, cover_count=2)
		service.add_item(order, item=ITEM, qty=1)

		self.assertEqual(order.items[0].rate, 25)

	def test_the_catalog_carries_the_other_list_so_the_till_can_price_offline(self):
		"""09 §3 — the app cannot fetch delivery prices during an outage."""
		payload = session.load_pos_session(self.profile, device_token=test_fixtures.DEVICE_TOKEN)
		row = next(entry for entry in payload["items"] if entry["item_code"] == ITEM)

		self.assertEqual(row["rate"], 25, "the terminal's own price stays on `rate`")
		self.assertEqual(row["rates"][DELIVERY_LIST], DELIVERY_RATE)

	def test_the_order_type_reports_its_list_to_the_app(self):
		payload = session.load_pos_session(self.profile, device_token=test_fixtures.DEVICE_TOKEN)
		row = next(entry for entry in payload["order_types"] if entry["name"] == self.order_type)

		self.assertEqual(row["selling_price_list"], DELIVERY_LIST)

	def test_a_second_price_list_costs_one_query_not_one_per_item(self):
		"""04 §8 — login is the slowest screen; one query per list, never per item.

		This counts `Item Price` reads rather than every query: a cold call warms
		several Frappe caches and would make any total meaningless.
		"""
		real_get_all = frappe.get_all
		seen = []

		def counting(*args, **kwargs):
			seen.append(args[0] if args else kwargs.get("doctype"))
			return real_get_all(*args, **kwargs)

		# Warm the caches first, so this measures queries and not cache misses.
		session.load_pos_session(self.profile, device_token=test_fixtures.DEVICE_TOKEN)

		frappe.get_all = counting
		try:
			session.load_pos_session(self.profile, device_token=test_fixtures.DEVICE_TOKEN)
		finally:
			frappe.get_all = real_get_all

		self.assertEqual(
			seen.count("Item Price"),
			1,
			"the catalogue read Item Price more than once for two price lists",
		)

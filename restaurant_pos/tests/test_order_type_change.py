# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Changing an order's type.

An order changes type only when the parties to the sale do not. Getting this
wrong moves a platform's debt onto a walk-in customer — or, the other way, hands
a delivery platform a bill it never took an order for.

The second half of the file is the money: a type that sells from another price
list has to re-price every line, or the till quietly charges dining-room prices
for a delivery order all day.

Refs: D-038, D-036, FR-1.6, FR-2.1
"""

import frappe

from restaurant_pos.tests.test_order import ITEM, TEST_ITEM_RATE, OrderTestBase
from restaurant_pos.utils import order as service

#: The delivery platform's own list, priced above the dining room's.
APP_LIST = "RPOS Test App List"
APP_RATE = 40.0


class OrderTypeChangeBase(OrderTestBase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.delivery = frappe.db.get_value("Restaurant Order Type", {"title": "Delivery"}, "name")
		cls.app_type = frappe.db.get_value("Restaurant Order Type", {"title": "HungerStation"}, "name")

		if not frappe.db.exists("Price List", APP_LIST):
			frappe.get_doc(
				{
					"doctype": "Price List",
					"price_list_name": APP_LIST,
					"currency": "SAR",
					"selling": 1,
					"enabled": 1,
				}
			).insert(ignore_permissions=True)

		existing = frappe.db.get_value("Item Price", {"item_code": ITEM, "price_list": APP_LIST}, "name")
		if existing:
			frappe.db.set_value("Item Price", existing, "price_list_rate", APP_RATE)
		else:
			frappe.get_doc(
				{
					"doctype": "Item Price",
					"item_code": ITEM,
					"price_list": APP_LIST,
					"selling": 1,
					"price_list_rate": APP_RATE,
				}
			).insert(ignore_permissions=True)

		frappe.db.commit()

	def setUp(self):
		# The right is what the shipped POS Manager has; the tests run as
		# Administrator, so this only matters where a refusal is asserted.
		frappe.db.set_value("Restaurant Order Type", self.app_type, "counterparty", "account")
		frappe.clear_cache(doctype="Restaurant Order Type")

	def _free_table(self) -> str:
		table = frappe.db.get_value("Restaurant Table", {"section": self.section, "is_active": 1}, "name")
		frappe.db.set_value("Restaurant Table", table, {"status": "available", "current_order": None})
		return table


class TestWhatMayBeConverted(OrderTypeChangeBase):
	def test_takeaway_becomes_dine_in(self):
		"""The everyday case: the customer decides to sit down."""
		table = self._free_table()
		order = self._order()
		service.add_item(order, item=self.item, qty=1)

		service.change_order_type(order, order_type=self.dine_in, table=table, cover_count=2)

		self.assertEqual(order.order_type, self.dine_in)
		self.assertEqual(order.table, table)
		self.assertEqual(frappe.db.get_value("Restaurant Table", table, "status"), "occupied")

	def test_leaving_dine_in_frees_the_table(self):
		table = self._free_table()
		order = self._order(order_type=self.dine_in, table=table, cover_count=2)
		service.add_item(order, item=self.item, qty=1)

		service.change_order_type(order, order_type=self.order_type)

		self.assertIsNone(order.table)
		self.assertEqual(frappe.db.get_value("Restaurant Table", table, "status"), "available")
		self.assertIsNone(frappe.db.get_value("Restaurant Table", table, "current_order"))

	def test_an_app_order_cannot_become_a_walk_in_one(self):
		"""D-038 — the platform is owed the money, not the person at the counter."""
		order = self._order()
		frappe.db.set_value("Restaurant Order", order.name, "order_type", self.app_type)
		order.reload()

		with self.assertRaises(frappe.ValidationError):
			service.change_order_type(order, order_type=self.order_type)

	def test_a_walk_in_order_cannot_become_an_app_one(self):
		"""There is no platform order behind it to be paid against."""
		order = self._order()

		with self.assertRaises(frappe.ValidationError):
			service.change_order_type(order, order_type=self.app_type)

	def test_one_app_cannot_become_another(self):
		"""The order arrived through one platform and cannot be claimed from another.

		This is the case the earlier "same settlement kind" rule got wrong: both
		are credit, and both are still impossible.
		"""
		jahez = frappe.db.get_value("Restaurant Order Type", {"title": "Jahez"}, "name")
		frappe.db.set_value("Restaurant Order Type", jahez, "counterparty", "account")
		frappe.clear_cache(doctype="Restaurant Order Type")

		order = self._order()
		frappe.db.set_value("Restaurant Order", order.name, "order_type", self.app_type)
		order.reload()

		with self.assertRaises(frappe.ValidationError):
			service.change_order_type(order, order_type=jahez)

	def test_a_closed_order_is_not_converted(self):
		order = self._order()
		service.add_item(order, item=self.item, qty=1)
		frappe.db.set_value("Restaurant Order", order.name, "status", "closed")
		order.reload()

		with self.assertRaises(frappe.ValidationError):
			service.change_order_type(order, order_type=self.dine_in)

	def test_converting_to_the_same_type_changes_nothing(self):
		order = self._order()
		outcome = service.change_order_type(order, order_type=self.order_type)
		self.assertFalse(outcome["changed"])

	def test_dine_in_without_a_table_is_refused(self):
		order = self._order()
		with self.assertRaises(frappe.ValidationError):
			service.change_order_type(order, order_type=self.dine_in, cover_count=2)


class TestConversionRePrices(OrderTypeChangeBase):
	def setUp(self):
		super().setUp()
		frappe.db.set_value("Restaurant Order Type", self.delivery, "selling_price_list", APP_LIST)
		frappe.clear_cache(doctype="Restaurant Order Type")

	def tearDown(self):
		frappe.db.set_value("Restaurant Order Type", self.delivery, "selling_price_list", None)
		frappe.clear_cache(doctype="Restaurant Order Type")

	def test_every_line_moves_to_the_new_list(self):
		"""D-036 — the list an order sells from is part of what its type means."""
		order = self._order()
		service.add_item(order, item=self.item, qty=2)
		self.assertEqual(order.items[0].rate, TEST_ITEM_RATE)

		outcome = service.change_order_type(order, order_type=self.delivery)

		self.assertEqual(order.items[0].rate, APP_RATE)
		self.assertEqual(order.items[0].amount, APP_RATE * 2)
		self.assertEqual(len(outcome["repriced_lines"]), 1)
		self.assertEqual(outcome["repriced_lines"][0]["was"], TEST_ITEM_RATE)
		self.assertEqual(outcome["repriced_lines"][0]["now"], APP_RATE)

	def test_the_total_follows_the_new_rates(self):
		order = self._order()
		service.add_item(order, item=self.item, qty=1)
		before = order.total_amount

		service.change_order_type(order, order_type=self.delivery)

		self.assertGreater(order.total_amount, before)
		self.assertEqual(order.subtotal, APP_RATE)

	def test_a_voided_line_is_left_alone(self):
		"""BR-013 keeps the row for the trail; it is not part of the sale."""
		order = self._order()
		service.add_item(order, item=self.item, qty=1)
		service.add_item(order, item=self.item, qty=1)
		service.void_item(order, item_idx=1, reason="test")

		service.change_order_type(order, order_type=self.delivery)

		self.assertEqual(order.items[0].rate, TEST_ITEM_RATE)
		self.assertEqual(order.items[1].rate, APP_RATE)

	def test_the_preview_shows_both_figures_and_saves_nothing(self):
		order = self._order()
		service.add_item(order, item=self.item, qty=1)

		preview = service.preview_order_type_change(order, order_type=self.delivery)

		self.assertEqual(preview["total_before"], order.total_amount)
		self.assertGreater(preview["total_after"], preview["total_before"])
		self.assertEqual(preview["price_list"], APP_LIST)

		order.reload()
		self.assertEqual(order.order_type, self.order_type)
		self.assertEqual(order.items[0].rate, TEST_ITEM_RATE)

	def test_an_item_missing_from_the_new_list_is_refused(self):
		"""Converting must never quietly make an item free."""
		order = self._order()
		service.add_item(order, item=self.item, qty=1)

		price = frappe.db.get_value("Item Price", {"item_code": ITEM, "price_list": APP_LIST}, "name")
		frappe.db.set_value("Item Price", price, "selling", 0)
		try:
			with self.assertRaises(frappe.ValidationError):
				service.change_order_type(order, order_type=self.delivery)
		finally:
			frappe.db.set_value("Item Price", price, "selling", 1)


class TestConversionIsAudited(OrderTypeChangeBase):
	def test_an_entry_records_both_types(self):
		"""Unlike a quantity change, this one decides what the customer pays."""
		table = self._free_table()
		order = self._order()
		service.add_item(order, item=self.item, qty=1)

		service.change_order_type(order, order_type=self.dine_in, table=table, cover_count=2)

		entry = frappe.get_all(
			"POS Audit Log",
			filters={"restaurant_order": order.name, "action_type": "order_type_changed"},
			fields=["name", "details"],
			limit=1,
		)
		self.assertTrue(entry, "no audit entry for the conversion")

		details = frappe.parse_json(entry[0].details)
		self.assertEqual(details["from"]["order_type"], self.order_type)
		self.assertEqual(details["to"]["order_type"], self.dine_in)


class TestConversionAsksForWhatItNeeds(OrderTypeChangeBase):
	"""FR-2.1a — a target that counts guests must be given a number.

	The screen asks for it in the dialog; the server refuses without it. Both
	halves matter: the dialog knowing is what stops the cashier meeting a red
	message with nowhere to answer it.
	"""

	def setUp(self):
		super().setUp()
		self.original = frappe.db.get_value(
			"Restaurant Order Type", self.dine_in, ["requires_table", "requires_cover_count"], as_dict=True
		)
		frappe.db.set_value(
			"Restaurant Order Type", self.dine_in, {"requires_table": 0, "requires_cover_count": 1}
		)
		frappe.clear_cache(doctype="Restaurant Order Type")

	def tearDown(self):
		frappe.db.set_value("Restaurant Order Type", self.dine_in, dict(self.original))
		frappe.clear_cache(doctype="Restaurant Order Type")

	def test_the_preview_says_a_count_is_wanted(self):
		"""What the dialog reads to decide whether to ask."""
		order = self._order()
		service.add_item(order, item=self.item, qty=1)

		preview = service.preview_order_type_change(order, order_type=self.dine_in)

		self.assertTrue(preview["requires_cover_count"])
		self.assertFalse(preview["requires_table"])

	def test_converting_without_a_count_is_refused(self):
		order = self._order()
		service.add_item(order, item=self.item, qty=1)

		with self.assertRaises(frappe.ValidationError):
			service.change_order_type(order, order_type=self.dine_in)

	def test_converting_with_a_count_is_accepted(self):
		order = self._order()
		service.add_item(order, item=self.item, qty=1)

		service.change_order_type(order, order_type=self.dine_in, cover_count=3)

		self.assertEqual(order.order_type, self.dine_in)
		self.assertEqual(order.cover_count, 3)

	def test_a_count_already_on_the_order_is_kept(self):
		"""An order that was seated once does not get asked twice."""
		order = self._order(cover_count=5)
		service.add_item(order, item=self.item, qty=1)

		service.change_order_type(order, order_type=self.dine_in)

		self.assertEqual(order.cover_count, 5)

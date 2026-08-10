# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Delivery-app order types.

Refs: 02_Business_Requirements.md §3, BR-002, BR-004, FR-1.1
"""

import frappe
from frappe.utils import flt

from restaurant_pos.setup.defaults import DELIVERY_APPS, create_default_data
from restaurant_pos.tests.test_payment import CASH, PaymentTestBase
from restaurant_pos.utils import order as orders
from restaurant_pos.utils import payment as payment_service


class TestAppOrderTypes(PaymentTestBase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		create_default_data()
		cls.hunger = frappe.db.get_value("Restaurant Order Type", {"title": "HungerStation"}, "name")
		frappe.db.commit()

	def test_every_app_from_the_spec_is_shipped(self):
		"""02 §3 lists HungerStation, Jahez and Talabat."""
		for app in DELIVERY_APPS:
			self.assertTrue(
				frappe.db.exists("Restaurant Order Type", {"title": app["title"]}),
				f"{app['title']} is missing",
			)
			self.assertTrue(
				frappe.db.exists("Mode of Payment", app["title"]),
				f"{app['title']} has no payment method",
			)

	def test_they_ship_inactive_pending_the_aggregator_customer(self):
		"""D-028 — the restaurant links its own receivable before going live."""
		for app in DELIVERY_APPS:
			config = frappe.get_doc("Restaurant Order Type", {"title": app["title"]})
			self.assertEqual(config.is_active, 0)
			self.assertEqual(config.customer_mode, "pre_set")
			self.assertIsNone(config.pre_set_customer)

	def test_activating_without_a_customer_is_refused(self):
		config = frappe.get_doc("Restaurant Order Type", self.hunger)
		config.is_active = 1

		with self.assertRaises(frappe.ValidationError):
			config.save(ignore_permissions=True)

	def test_the_payment_method_is_forced(self):
		"""BR-002 — a cashier cannot take cash for an app order."""
		config = frappe.get_doc("Restaurant Order Type", self.hunger)
		self.assertEqual(len(config.allowed_payment_methods), 1)
		self.assertEqual(config.allowed_payment_methods[0].payment_method, "HungerStation")
		self.assertEqual(config.allowed_payment_methods[0].is_forced, 1)

	def test_the_app_order_number_is_required(self):
		"""BR-004 / FR-1.2."""
		config = frappe.get_doc("Restaurant Order Type", self.hunger)
		self.assertEqual(len(config.additional_fields), 1)
		self.assertEqual(config.additional_fields[0].is_required, 1)
		self.assertEqual(config.additional_fields[0].field_label_ar, "رقم الطلب في التطبيق")

	# ------------------------------------------------------------ behaviour

	def _activated_app_order(self):
		"""Activate HungerStation the way a restaurant would, then open an order."""
		customer = frappe.db.get_value("POS Profile", self.profile, "customer")
		config = frappe.get_doc("Restaurant Order Type", self.hunger)
		config.pre_set_customer = customer
		config.is_active = 1
		config.save(ignore_permissions=True)
		frappe.clear_cache(doctype="Restaurant Order Type")

		order = orders.create_order(
			order_type=self.hunger,
			pos_profile=self.profile,
			order_type_data={"App Order No": "HS-29541"},
		)
		orders.add_item(order, item="RPOS-TEST-BURGER", qty=1)
		order.reload()
		return order, customer

	def test_the_app_dictates_the_customer(self):
		"""BR-002 — whatever the client sends for customer is ignored."""
		order, customer = self._activated_app_order()
		self.assertEqual(order.customer, customer)

	def test_the_app_order_number_must_be_supplied(self):
		customer = frappe.db.get_value("POS Profile", self.profile, "customer")
		config = frappe.get_doc("Restaurant Order Type", self.hunger)
		config.pre_set_customer = customer
		config.is_active = 1
		config.save(ignore_permissions=True)
		frappe.clear_cache(doctype="Restaurant Order Type")

		with self.assertRaises(frappe.ValidationError):
			orders.create_order(order_type=self.hunger, pos_profile=self.profile)

	def test_cash_is_refused_for_an_app_order(self):
		"""BR-002 — money the platform also pays out must not enter the till."""
		order, _customer = self._activated_app_order()

		with self.assertRaises(frappe.ValidationError):
			payment_service.process_payment(
				order, payments=[{"method": CASH, "amount": flt(order.total_amount)}]
			)

	def test_the_forced_method_settles_it(self):
		order, _customer = self._activated_app_order()

		result = payment_service.process_payment(
			order,
			payments=[{"method": "HungerStation", "amount": flt(order.total_amount)}],
		)

		self.assertTrue(result["sales_invoice"])
		self.assertEqual(order.status, "closed")

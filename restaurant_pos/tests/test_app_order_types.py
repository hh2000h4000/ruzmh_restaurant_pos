# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Delivery-app order types.

Refs: 02_Business_Requirements.md §3, BR-002, BR-004, FR-1.1
"""

import frappe
from frappe.utils import flt

from restaurant_pos.setup import platform_accounts
from restaurant_pos.setup.defaults import DELIVERY_APPS, create_default_data
from restaurant_pos.tests.test_payment import CASH, PaymentTestBase
from restaurant_pos.utils import order as orders
from restaurant_pos.utils import payment as payment_service
from restaurant_pos.utils import posting
from restaurant_pos.utils.sale_doc import SALE


class TestAppOrderTypes(PaymentTestBase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		create_default_data()
		cls.hunger = frappe.db.get_value("Restaurant Order Type", {"title": "HungerStation"}, "name")
		cls.customer = frappe.db.get_value("POS Profile", cls.profile, "customer")
		cls.company = frappe.db.get_value("POS Profile", cls.profile, "company")

		# What a migrate does on a real site: each platform's method gets the
		# account that holds what the platform owes (`D-319`).
		platform_accounts.setup(cls.company)

		frappe.db.commit()

	def tearDown(self):
		"""Leave the shipped state as found.

		Several tests here activate HungerStation, and one asserts that it ships
		inactive. Without this the suite would pass or fail on alphabetical
		ordering.
		"""
		super().tearDown()
		for app in DELIVERY_APPS:
			name = frappe.db.get_value("Restaurant Order Type", {"title": app["title"]}, "name")
			if name:
				frappe.db.set_value("Restaurant Order Type", name, {"is_active": 0, "pre_set_customer": None})
		frappe.clear_cache(doctype="Restaurant Order Type")
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

	def _activate(self):
		config = frappe.get_doc("Restaurant Order Type", self.hunger)
		config.pre_set_customer = self.customer
		config.is_active = 1
		config.save(ignore_permissions=True)
		frappe.clear_cache(doctype="Restaurant Order Type")

	def _activated_app_order(self):
		"""Activate HungerStation the way a restaurant would, then open an order."""
		customer = self.customer
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
		self._activate()

		with self.assertRaises(frappe.ValidationError):
			orders.create_order(order_type=self.hunger, pos_profile=self.profile)

	def test_cash_is_refused_for_an_app_order(self):
		"""BR-002 — money the platform also pays out must not enter the till."""
		order, _customer = self._activated_app_order()

		with self.assertRaises(frappe.ValidationError):
			payment_service.process_payment(
				order, payments=[{"method": CASH, "amount": flt(order.total_amount)}]
			)

	def test_the_platform_owes_the_money_it_already_took(self):
		"""D-029 — an app order is credit: nothing enters the till.

		The customer paid HungerStation, not the restaurant. The bill is paid —
		with the platform's method — and what the platform owes sits on that
		method's account until its transfer lands (`D-319`).
		"""
		order, customer = self._activated_app_order()
		total = flt(order.total_amount)

		result = payment_service.process_payment(
			order, payments=[{"method": "HungerStation", "amount": total}]
		)

		self.assertEqual(result["settlement"], "credit")
		self.assertEqual(order.status, "closed")

		invoice = frappe.get_doc(SALE, result["sales_invoice"])
		self.assertEqual(invoice.docstatus, 1)
		self.assertEqual(invoice.customer, customer)
		(paid,) = invoice.payments
		self.assertEqual(paid.mode_of_payment, "HungerStation")
		self.assertAlmostEqual(flt(paid.amount), total, places=2)
		self.assertAlmostEqual(flt(invoice.outstanding_amount), 0, places=2)

	def test_and_the_day_s_posting_puts_it_on_the_platform_s_account(self):
		"""The accountant reads what HungerStation owes off one account, and clears it there."""
		order, _customer = self._activated_app_order()
		total = flt(order.total_amount)
		payment_service.process_payment(order, payments=[{"method": "HungerStation", "amount": total}])
		account = frappe.db.get_value(
			"Mode of Payment Account", {"parent": "HungerStation", "company": self.company}, "default_account"
		)
		# An asset, and not a Receivable: that type wants a customer on every line.
		root, kind = frappe.db.get_value("Account", account, ["root_type", "account_type"])
		self.assertEqual((root, kind or ""), ("Asset", ""))

		batch = frappe.get_doc(posting.BATCH, posting.post_branch(order.branch)[-1])

		self.assertEqual(batch.status, "Posted", batch.error)
		owed = frappe.get_all(
			"GL Entry",
			filters={"voucher_no": batch.sales_invoice, "account": account, "is_cancelled": 0},
			fields=["sum(debit) as debit", "sum(credit) as credit"],
		)[0]
		self.assertAlmostEqual(flt(owed.debit) - flt(owed.credit), total, places=2)

	def test_a_platform_the_restaurant_added_says_it_needs_an_account(self):
		order, _customer = self._activated_app_order()
		frappe.db.delete("Mode of Payment Account", {"parent": "HungerStation"})

		try:
			with self.assertRaises(frappe.ValidationError) as refused:
				payment_service.process_payment(
					order, payments=[{"method": "HungerStation", "amount": flt(order.total_amount)}]
				)
		finally:
			# This class's tearDown commits: the account must be back before it does.
			frappe.db.rollback()

		self.assertIn("HungerStation", str(refused.exception))

	def test_a_credit_method_is_not_a_bank_transfer(self):
		"""The original mistake: shipping these as Bank, which put them in the drawer's count.

		They are General and marked credit, so no drawer expects them — and each
		ships with the account that holds what its platform owes (`D-319`).
		"""
		for app in DELIVERY_APPS:
			method = frappe.get_doc("Mode of Payment", app["title"])
			self.assertEqual(method.rpos_is_credit, 1)
			self.assertEqual(method.type, "General")

	def test_till_and_credit_cannot_be_mixed(self):
		order, _customer = self._activated_app_order()
		half = flt(order.total_amount) / 2

		with self.assertRaises(frappe.ValidationError):
			payment_service.process_payment(
				order,
				payments=[
					{"method": "HungerStation", "amount": half},
					{"method": CASH, "amount": half},
				],
			)

	def test_corporate_ships_and_is_credit(self):
		"""02 §3 — restored: BR-022 never forbade credit, only partial payment."""
		config = frappe.get_doc("Restaurant Order Type", {"title": "Corporate"})
		self.assertEqual(config.customer_mode, "required")
		self.assertEqual(config.allowed_payment_methods[0].payment_method, "Credit")
		self.assertEqual(config.allowed_payment_methods[0].is_forced, 1)

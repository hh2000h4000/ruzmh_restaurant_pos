# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Payment and Sales Invoice tests.

Refs: BR-016, BR-020..BR-024, FR-2.7, FR-10.2, FR-10.3, FR-10.4
"""

import uuid

import frappe
from frappe.utils import flt

from restaurant_pos.restaurant_pos.api import payment as api
from restaurant_pos.restaurant_pos.tests.test_order import ITEM, OrderTestBase
from restaurant_pos.restaurant_pos.utils import order as orders
from restaurant_pos.restaurant_pos.utils import payment as service
from restaurant_pos.restaurant_pos.utils import totals

CASH = "Cash"


class PaymentTestBase(OrderTestBase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		profile = frappe.get_doc("POS Profile", cls.profile)

		if not profile.customer:
			customer = frappe.db.get_value("Customer", {}, "name") or (
				frappe.get_doc(
					{
						"doctype": "Customer",
						"customer_name": "RPOS Walk-in",
						"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
						"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
			frappe.db.set_value("POS Profile", cls.profile, "customer", customer)

		if not profile.warehouse:
			frappe.db.set_value(
				"POS Profile",
				cls.profile,
				"warehouse",
				frappe.db.get_value("Warehouse", {"company": profile.company, "is_group": 0}, "name"),
			)

		# BR-024 — the Saudi 0.05 step, the same one ERPNext will use.
		frappe.db.set_value("Currency", "SAR", "smallest_currency_fraction_value", 0.05)
		frappe.clear_cache()
		frappe.db.commit()

	def _payable_order(self, qty=1):
		order = self._order()
		orders.add_item(order, item=ITEM, qty=qty)
		order.reload()
		return order

	def _pay(self, order, amount=None, tendered=None, **kwargs):
		amount = flt(order.total_amount) if amount is None else amount
		row = {"method": CASH, "amount": amount}
		if tendered is not None:
			row["tendered"] = tendered
		return service.process_payment(order, payments=[row], **kwargs)


class TestPaymentValidation(PaymentTestBase):
	def test_an_empty_order_cannot_be_paid(self):
		order = self._order()
		with self.assertRaises(frappe.ValidationError):
			self._pay(order, amount=10)

	def test_partial_payment_is_refused(self):
		"""BR-022 — v1 has no partial payment."""
		order = self._payable_order()
		with self.assertRaises(frappe.ValidationError):
			self._pay(order, amount=flt(order.total_amount) - 5)

	def test_a_zero_or_negative_amount_is_refused(self):
		order = self._payable_order()
		for bad in (0, -10):
			with self.assertRaises(frappe.ValidationError):
				self._pay(order, amount=bad)

	def test_an_unknown_payment_method_is_refused(self):
		order = self._payable_order()
		with self.assertRaises(frappe.ValidationError):
			service.process_payment(order, payments=[{"method": "Camel", "amount": flt(order.total_amount)}])

	def test_change_is_the_difference_from_what_was_handed_over(self):
		"""BR-021 / FR-10.3."""
		order = self._payable_order()
		due = flt(order.total_amount)

		result = self._pay(order, amount=due, tendered=100)

		self.assertAlmostEqual(result["change_amount"], totals.money(100 - due), places=2)

	def test_multiple_methods_settle_one_order(self):
		"""BR-020 / FR-10.2."""
		order = self._payable_order(qty=2)
		due = flt(order.total_amount)
		half = totals.money(due / 2)

		result = service.process_payment(
			order,
			payments=[
				{"method": CASH, "amount": half},
				{"method": CASH, "amount": totals.money(due - half)},
			],
		)

		invoice = frappe.get_doc("Sales Invoice", result["sales_invoice"])
		self.assertEqual(len(invoice.payments), 2)


class TestSalesInvoice(PaymentTestBase):
	def test_payment_submits_an_invoice_and_closes_the_order(self):
		"""BR-016 / FR-2.7."""
		order = self._payable_order()
		result = self._pay(order)

		invoice = frappe.get_doc("Sales Invoice", result["sales_invoice"])
		self.assertEqual(invoice.docstatus, 1)
		self.assertEqual(invoice.is_pos, 1)
		self.assertEqual(order.status, "closed")
		self.assertEqual(order.sales_invoice, invoice.name)
		self.assertIsNotNone(order.closed_at)

	def test_no_separate_payment_entry_is_created(self):
		"""D-022 — is_pos settles the invoice; a Payment Entry would pay it twice."""
		order = self._payable_order()
		result = self._pay(order)

		self.assertEqual(
			frappe.db.count(
				"Payment Entry Reference",
				{"reference_doctype": "Sales Invoice", "reference_name": result["sales_invoice"]},
			),
			0,
		)

	def test_the_invoice_is_left_outstanding_nothing(self):
		order = self._payable_order()
		result = self._pay(order)

		invoice = frappe.get_doc("Sales Invoice", result["sales_invoice"])
		self.assertAlmostEqual(flt(invoice.outstanding_amount), 0, places=2)

	def test_voided_lines_do_not_reach_the_invoice(self):
		order = self._payable_order(qty=1)
		orders.add_item(order, item=ITEM, qty=1)
		orders.void_item(order, item_idx=2, reason="Changed mind")

		result = self._pay(order)
		invoice = frappe.get_doc("Sales Invoice", result["sales_invoice"])
		self.assertEqual(len(invoice.items), 1)

	def test_the_order_total_matches_the_invoice(self):
		"""D-018 / D-023 — the screen and the ledger must agree to the halala."""
		order = self._payable_order(qty=3)
		expected = flt(order.total_amount)

		result = self._pay(order)
		invoice = frappe.get_doc("Sales Invoice", result["sales_invoice"])

		self.assertAlmostEqual(flt(invoice.rounded_total or invoice.grand_total), expected, places=2)
		self.assertAlmostEqual(result["total_amount"], expected, places=2)

	def test_the_invoice_links_back_to_the_order(self):
		order = self._payable_order()
		result = self._pay(order)
		invoice = frappe.get_doc("Sales Invoice", result["sales_invoice"])
		self.assertIn(order.name, invoice.remarks or "")


class TestPaymentSideEffects(PaymentTestBase):
	def test_a_paid_order_cannot_be_paid_again(self):
		"""The duplicate-invoice guard, independent of queue_id."""
		order = self._payable_order()
		self._pay(order)

		with self.assertRaises(frappe.ValidationError):
			api.process_payment(order.name, payments=[{"method": CASH, "amount": flt(order.total_amount)}])

	def test_a_paid_order_cannot_be_modified(self):
		"""BR-017."""
		order = self._payable_order()
		self._pay(order)
		order.reload()

		with self.assertRaises(frappe.ValidationError):
			orders.add_item(order, item=ITEM, qty=1)

	def test_the_table_goes_to_cleaning(self):
		"""FR-2.7g."""
		table = frappe.db.get_value("Restaurant Table", {"section": self.section}, "name")
		frappe.db.set_value("Restaurant Table", table, {"status": "available", "current_order": None})

		order = self._order(order_type=self.dine_in, table=table, cover_count=2)
		orders.add_item(order, item=ITEM, qty=1)
		order.reload()
		self._pay(order)

		self.assertEqual(frappe.db.get_value("Restaurant Table", table, "status"), "cleaning")

	def test_a_send_on_payment_order_type_reaches_the_kitchen(self):
		"""FR-2.7e — Takeaway holds its ticket until the customer has paid."""
		self.assertEqual(
			frappe.db.get_value("Restaurant Order Type", self.order_type, "send_to_kitchen_on"),
			"payment",
		)

		order = self._payable_order()
		grill = frappe.db.get_value("Production Center", {"title": "RPOS Test Grill"}, "name")
		order.items[0].production_center = grill
		order.save(ignore_permissions=True)

		result = self._pay(order)

		self.assertEqual(len(result["kots_created"]), 1)
		self.assertEqual(frappe.db.count("Kitchen Order Ticket", {"restaurant_order": order.name}), 1)


class TestPaymentDiscount(PaymentTestBase):
	def test_discount_within_the_limit_is_applied_and_audited(self):
		"""FR-10.4 — the invoice discounts the net, so ERPNext recomputes VAT."""
		order = self._payable_order(qty=4)

		# Recalculate what will be due once the discount lands.
		order.discount_type = "percentage"
		order.discount_value = 10
		totals.calculate(order)
		due = flt(order.total_amount)
		order.discount_type = None
		order.discount_value = 0

		result = service.process_payment(
			order,
			payments=[{"method": CASH, "amount": due}],
			discount_type="percentage",
			discount_value=10,
		)

		invoice = frappe.get_doc("Sales Invoice", result["sales_invoice"])
		self.assertEqual(invoice.apply_discount_on, "Net Total")
		self.assertGreater(flt(invoice.discount_amount), 0)

		self.assertTrue(
			frappe.get_all(
				"POS Audit Log",
				filters={"restaurant_order": order.name, "action_type": "discount_applied"},
			)
		)


class TestPaymentIdempotency(PaymentTestBase):
	def test_replaying_a_payment_creates_one_invoice(self):
		"""09 §8 — the single most damaging replay in the system."""
		order = self._payable_order()
		queue_id = str(uuid.uuid4())
		amount = flt(order.total_amount)

		first = api.process_payment(
			order.name, payments=[{"method": CASH, "amount": amount}], queue_id=queue_id
		)
		second = api.process_payment(
			order.name, payments=[{"method": CASH, "amount": amount}], queue_id=queue_id
		)

		self.assertEqual(first["sales_invoice"], second["sales_invoice"])
		self.assertTrue(second.get("already_processed"))
		self.assertEqual(frappe.db.count("Sales Invoice", {"remarks": ("like", f"%{order.name}%")}), 1)

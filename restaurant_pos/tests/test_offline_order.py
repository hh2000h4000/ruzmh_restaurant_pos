# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""An order sold while the line was down (09 §5, D-072).

The dangerous tests in this file are the two about money: that a bill the till
priced correctly lands exactly once, and that a bill it priced differently lands
**not at all** rather than at whichever figure happened to be reached first.

Refs: 09 §5, §8, D-071, D-072
"""

import frappe

from restaurant_pos.api import offline as api
from restaurant_pos.tests.test_order import ITEM, TEST_ITEM_RATE, OrderTestBase
from restaurant_pos.tests.test_payment import CASH, _ensure_fiscal_year
from restaurant_pos.utils import totals
from restaurant_pos.utils.sale_doc import SALE


class OfflineTestBase(OrderTestBase):
	def setUp(self):
		_ensure_fiscal_year()

	def _payload(self, qty: float = 2, **overrides) -> dict:
		"""What the till composed offline, priced with the shipped inputs."""
		pricing = totals.pricing_inputs(self.profile)
		figures = totals.compute([TEST_ITEM_RATE * qty], None, 0, pricing)

		payload = {
			"order_type": self.order_type,
			"lines": [{"item": ITEM, "qty": qty}],
			"discount_type": None,
			"discount_value": 0,
			"payments": [{"method": CASH, "amount": figures["total_amount"]}],
			"totals": figures,
			"pricing": pricing,
		}
		payload.update(overrides)
		return payload


class TestABillSoldOffline(OfflineTestBase):
	def test_it_lands_as_a_real_order_and_a_real_invoice(self):
		result = api.submit_order(
			pos_profile=self.profile, payload=self._payload(), queue_id=frappe.generate_hash()
		)

		order = frappe.get_doc("Restaurant Order", result["order_name"])
		self.assertEqual(order.status, "closed")
		self.assertEqual(order.is_offline_order, 1)
		self.assertTrue(order.sales_invoice)
		self.assertEqual(frappe.db.get_value(SALE, order.sales_invoice, "docstatus"), 1)

	def test_the_totals_it_quoted_are_the_totals_it_gets(self):
		"""D-071 — the contract's whole purpose, end to end."""
		payload = self._payload(qty=3)

		result = api.submit_order(pos_profile=self.profile, payload=payload, queue_id=frappe.generate_hash())

		self.assertTrue(result["variance"]["agreed"])
		self.assertEqual(result["variance"]["difference"], 0.0)
		self.assertEqual(result["total_amount"], payload["totals"]["total_amount"])

	def test_a_price_typed_offline_lands_at_that_price(self):
		"""D-378 — an open price is in no list, so the line carries it."""
		frappe.db.set_value("Item", ITEM, "rpos_open_price", 1)
		frappe.clear_document_cache("Item", ITEM)
		try:
			pricing = totals.pricing_inputs(self.profile)
			figures = totals.compute([40.0], None, 0, pricing)
			payload = self._payload(
				lines=[{"item": ITEM, "qty": 1, "rate": 40.0}],
				payments=[{"method": CASH, "amount": figures["total_amount"]}],
				totals=figures,
			)
			result = api.submit_order(
				pos_profile=self.profile, payload=payload, queue_id=frappe.generate_hash()
			)
		finally:
			frappe.db.set_value("Item", ITEM, "rpos_open_price", 0)
			frappe.clear_document_cache("Item", ITEM)

		order = frappe.get_doc("Restaurant Order", result["order_name"])
		self.assertEqual(order.items[0].rate, 40.0)
		self.assertTrue(result["variance"]["agreed"])

	def test_replaying_it_does_not_sell_it_twice(self):
		"""09 §8 — the most damaging replay in the system, on the riskiest path."""
		queue_id = frappe.generate_hash()
		payload = self._payload()

		first = api.submit_order(pos_profile=self.profile, payload=payload, queue_id=queue_id)
		second = api.submit_order(pos_profile=self.profile, payload=payload, queue_id=queue_id)

		self.assertEqual(first["order_name"], second["order_name"])
		self.assertEqual(first["sales_invoice"], second["sales_invoice"])
		self.assertTrue(second.get("already_processed"))

	def test_it_needs_a_queue_id(self):
		with self.assertRaises(frappe.ValidationError):
			api.submit_order(pos_profile=self.profile, payload=self._payload(), queue_id="")


class TestWhenTheFiguresDisagree(OfflineTestBase):
	def test_a_mismatched_bill_is_refused(self):
		"""D-072 — the money is already in the drawer, and that is not a reason
		to post whichever figure is at hand."""
		payload = self._payload()
		payload["totals"] = {**payload["totals"], "total_amount": payload["totals"]["total_amount"] + 5}

		with self.assertRaises(frappe.ValidationError):
			api.submit_order(pos_profile=self.profile, payload=payload, queue_id=frappe.generate_hash())

	def test_nothing_is_left_behind_when_it_is_refused(self):
		"""The rollback is the point: no half-posted order for somebody to find.

		A savepoint stands in for the request cycle. A real `frappe.throw` is
		followed by the handler rolling the request back; a test runs inside the
		suite's own transaction and would otherwise keep the order the refusal
		was supposed to undo — and rolling the *whole* transaction back would
		take every earlier test's work with it.
		"""
		payload = self._payload()
		payload["totals"] = {**payload["totals"], "total_amount": 1.0}
		queue_id = frappe.generate_hash()

		frappe.db.savepoint("offline_mismatch")
		with self.assertRaises(frappe.ValidationError):
			api.submit_order(pos_profile=self.profile, payload=payload, queue_id=queue_id)
		frappe.db.rollback(save_point="offline_mismatch")

		self.assertFalse(frappe.db.exists("Restaurant Order", {"offline_queue_id": queue_id}))
		self.assertFalse(frappe.db.exists("POS Sync Entry", {"queue_id": queue_id}))

	def test_a_bill_with_no_totals_is_refused(self):
		"""A payload that never says what it charged cannot be checked at all."""
		payload = self._payload()
		payload.pop("totals")

		with self.assertRaises(frappe.ValidationError):
			api.submit_order(pos_profile=self.profile, payload=payload, queue_id=frappe.generate_hash())

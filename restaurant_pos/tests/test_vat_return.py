# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The VAT return, box by box (`D-273`).

An accountant copies these figures onto ZATCA's form, so what is held is what
the form asks: a sale lands in box 1 with its VAT, a refund lands in the same
box as an adjustment, box 13 is sales VAT less purchase VAT, and the ledger's
VAT accounts move by exactly as much.

**Measured as differences** — the suite's own invoices pile up on the test site.

Refs: FR-11.2, D-273
"""

import frappe
from frappe.utils import flt, today

from restaurant_pos.restaurant_pos.report.vat_return import vat_return as report
from restaurant_pos.tests.test_order import BRANCH
from restaurant_pos.tests.test_payment import PaymentTestBase
from restaurant_pos.utils import posting, returns
from restaurant_pos.utils.sale_doc import SALE

REASON = "goods_returned"


class TestTheReturn(PaymentTestBase):
	def setUp(self):
		super().setUp()
		# The suite's terminal sells with no tax template, which is a site with
		# no VAT; a Saudi till carries the company's, as the user's does.
		company = frappe.db.get_value("POS Profile", self.profile, "company")
		template = frappe.db.get_value("Sales Taxes and Charges Template", {"company": company}, "name")
		was = frappe.db.get_value("POS Profile", self.profile, "taxes_and_charges")
		frappe.db.set_value("POS Profile", self.profile, "taxes_and_charges", template)
		self.addCleanup(frappe.db.set_value, "POS Profile", self.profile, "taxes_and_charges", was)

	def _boxes(self) -> dict[str, dict]:
		company = frappe.db.get_value("POS Profile", self.profile, "company")
		_columns, rows = report.execute({"company": company, "from_date": today(), "to_date": today()})
		return {row["box"] or "books": row for row in rows}

	def _sold(self, qty: float = 2):
		order = self._payable_order(qty=qty)
		self._pay(order)
		return order, frappe.get_doc(SALE, order.sales_invoice)

	def test_a_sale_lands_in_box_one_with_its_vat(self):
		before = self._boxes()
		_order, invoice = self._sold()
		after = self._boxes()

		self.assertAlmostEqual(
			after["1"]["amount"] - before["1"]["amount"], flt(invoice.base_net_total), places=2
		)
		self.assertAlmostEqual(
			after["1"]["vat"] - before["1"]["vat"], flt(invoice.base_total_taxes_and_charges), places=2
		)
		self.assertGreater(flt(invoice.base_total_taxes_and_charges), 0, "the suite's till must charge VAT")

	def test_a_refund_is_an_adjustment_in_the_same_box(self):
		order, _invoice = self._sold(qty=2)
		before = self._boxes()

		line = returns.returnable(order)["items"][0]["row"]
		refund = returns.create_return(order, items=[{"row": line, "qty": 1}], reason_code=REASON)
		credit = frappe.get_doc(SALE, refund["credit_note"])

		after = self._boxes()
		self.assertEqual(after["1"]["amount"], before["1"]["amount"], "a refund is not a sale")
		self.assertAlmostEqual(
			after["1"]["adjustment"] - before["1"]["adjustment"], flt(credit.base_net_total), places=2
		)
		self.assertLess(after["1"]["vat"] - before["1"]["vat"], 0)

	def test_box_thirteen_is_sales_vat_less_purchase_vat(self):
		self._sold()
		boxes = self._boxes()

		self.assertAlmostEqual(boxes["13"]["vat"], boxes["6"]["vat"] - boxes["12"]["vat"], places=2)

	def test_the_ledger_moves_with_box_thirteen(self):
		"""Once the day is posted (`D-313`): the return reads the tax documents, the
		books line reads the ledger, and the ledger is written by the posting."""
		posting.post_branch(BRANCH)
		before = self._boxes()
		self._sold()
		posting.post_branch(BRANCH)
		after = self._boxes()

		self.assertAlmostEqual(
			after["books"]["vat"] - before["books"]["vat"], after["13"]["vat"] - before["13"]["vat"], places=2
		)

	def test_what_the_system_does_not_hold_is_named_not_invented(self):
		boxes = self._boxes()

		for number in ("2", "4", "8", "9", "14", "15"):
			with self.subTest(box=number):
				self.assertEqual(boxes[number]["amount"], 0)
				self.assertTrue(boxes[number]["note"])

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The A4 invoice, the one an auditor is handed (`D-153`).

The till's receipt is a bitmap built by our own renderer; **this** is Frappe's
print engine over a Jinja template, and the two share nothing but the document.
So it needs its own tests: a template that raises produces a blank page, and a
template whose QR call is misspelled produces a page that looks complete and is
not compliant.

Refs: FR-7.7, D-092, D-153
"""

import frappe

from restaurant_pos.tests.test_returns import REASON, ReturnTestBase
from restaurant_pos.utils import returns as service

FORMAT = "RPOS Tax Invoice"


#: A number shaped like a real one — 15 digits, starting and ending in 3.
#:
#: The suite's company ships without one, and that is not an oversight to work
#: around here: a KSA company **has** a VAT number, and the QR is invalid
#: without it. So the fixture states it, and the one test about its absence
#: takes it away again.
TEST_VAT = "300000000000003"


class TestTheA4Invoice(ReturnTestBase):
	def setUp(self):
		super().setUp()
		self.company = frappe.db.get_value("POS Profile", self.profile, "company")
		self._set_vat(TEST_VAT)

	def tearDown(self):
		frappe.clear_document_cache("Company", self.company)
		super().tearDown()

	def _set_vat(self, number: str | None) -> None:
		"""Write it **and** drop the cached copy of the document.

		`invoice_qr` reads the company through `get_cached_doc`, and
		`db.set_value` writes past that cache — so a company whose VAT number
		was set this way still looks like one without. Alone, this module passed
		on a cold cache and hid it; in the full suite an earlier module had
		already cached the company, and the QR silently stopped appearing.

		`clear_cache(doctype=...)` is the wrong tool: it drops the **meta**, not
		the document. Nothing about production changes — a desk save clears the
		document cache itself — but a test that writes underneath it must say so.
		"""
		frappe.db.set_value("Company", self.company, "tax_id", number)
		frappe.clear_document_cache("Company", self.company)

	def _printed(self, invoice: str) -> str:
		return frappe.get_print("Sales Invoice", invoice, print_format=FORMAT)

	def test_the_format_is_installed_by_the_app(self):
		"""Shipped, not drawn by hand on one site."""
		self.assertTrue(frappe.db.exists("Print Format", FORMAT))
		self.assertEqual(frappe.db.get_value("Print Format", FORMAT, "standard"), "Yes")

	def test_a_sale_prints_as_a_simplified_tax_invoice(self):
		order = self._paid()
		html = self._printed(order.sales_invoice)

		self.assertIn("فاتورة ضريبية مبسطة", html)
		self.assertIn(order.sales_invoice, html)
		self.assertIn(TEST_VAT, html, "the seller's VAT number belongs on the paper")

	def test_it_carries_the_qr(self):
		"""**The whole reason this exists** (`D-153`).

		A copy printed from the desk had none: the QR was built inside the
		thermal renderer and reachable from nowhere else, so the paper an
		auditor is handed was missing the one thing they check first.
		"""
		order = self._paid()

		self.assertIn("data:image/png;base64", self._printed(order.sales_invoice))

	def test_a_credit_note_is_headed_as_one_and_names_the_bill_it_reverses(self):
		"""ZATCA treats it as its own document type, not an invoice."""
		order = self._paid()
		refund = service.create_return(order, items=[{"row": self._row(order), "qty": 1}], reason_code=REASON)

		html = self._printed(refund["credit_note"])
		self.assertIn("إشعار دائن", html)
		self.assertNotIn("فاتورة ضريبية مبسطة", html)
		self.assertIn(order.sales_invoice, html)

	def test_without_a_vat_number_it_says_so_instead_of_drawing_nothing(self):
		"""`D-074` — a QR that is quietly absent is the worst of the three.

		`invoice_qr` returns nothing when the company has no VAT number, because
		a QR missing that tag is invalid rather than lenient. The page has to say
		that out loud; a blank corner reads as a print that worked.
		"""
		order = self._paid()
		self._set_vat(None)

		html = self._printed(order.sales_invoice)
		self.assertNotIn("data:image/png;base64", html)
		self.assertIn("No QR", html)

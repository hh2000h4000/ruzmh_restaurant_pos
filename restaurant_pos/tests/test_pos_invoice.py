# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""A till sale is ERPNext's `POS Invoice`, with two checks asked our way (`D-312`).

What `test_a_day_at_the_till` proves by living through a day — a real cashier
takes payments — this pins by name, so a refusal here says which of the two
replaced checks came back.
"""

import frappe

from restaurant_pos.overrides.pos_invoice import RPOSInvoice
from restaurant_pos.tests.test_payment import CASH
from restaurant_pos.tests.test_returns import ReturnTestBase
from restaurant_pos.utils import shift as shift_service
from restaurant_pos.utils.sale_doc import SALE


class ATillSaleIsAPosInvoice(ReturnTestBase):
	def test_the_bill_a_till_sells_is_a_pos_invoice(self):
		order = self._paid()

		self.assertEqual(SALE, "POS Invoice")
		self.assertEqual(frappe.db.get_value("POS Invoice", order.sales_invoice, "docstatus"), 1)
		self.assertFalse(frappe.db.exists("Sales Invoice", order.sales_invoice))

	def test_erpnext_builds_it_through_our_controller(self):
		order = self._paid()

		self.assertIsInstance(frappe.get_doc("POS Invoice", order.sales_invoice), RPOSInvoice)

	def test_nothing_leaves_the_warehouse_at_the_sale(self):
		"""Stock is taken by the posting, from the recipe as the bill recorded it (`docs/14` §4.2)."""
		order = self._paid()
		invoice = frappe.get_doc("POS Invoice", order.sales_invoice)

		self.assertEqual(
			frappe.db.count(
				"Stock Ledger Entry", {"voucher_type": "POS Invoice", "voucher_no": invoice.name}
			),
			0,
		)

	def test_nothing_is_posted_to_the_books_at_the_sale(self):
		order = self._paid()

		self.assertEqual(frappe.db.count("GL Entry", {"voucher_no": order.sales_invoice}), 0)

	def test_it_is_paid_in_full_by_what_the_customer_handed_over(self):
		order = self._paid()
		invoice = frappe.get_doc("POS Invoice", order.sales_invoice)

		self.assertEqual([row.mode_of_payment for row in invoice.payments], [CASH])
		self.assertAlmostEqual(invoice.paid_amount, invoice.rounded_total or invoice.grand_total, places=2)

	def test_a_sale_is_refused_when_the_drawer_is_not_open(self):
		"""ERPNext's own rule, kept — only asked without needing to read the drawer."""
		order = self._paid()
		invoice = frappe.copy_doc(frappe.get_doc("POS Invoice", order.sales_invoice))
		till = shift_service.selling_till(self.profile).name
		frappe.db.set_value("POS Opening Entry", till, "status", "Closed")
		# The class rolls back once, at the end: left closed, every test after
		# this one is refused for having no shift.
		self.addCleanup(frappe.db.set_value, "POS Opening Entry", till, "status", "Open")

		with self.assertRaises(frappe.ValidationError) as refused:
			invoice.insert(ignore_permissions=True)

		self.assertIn("POS Opening Entry", str(refused.exception))


class TheDrawerClosesWithoutItsInvoices(ReturnTestBase):
	"""ERPNext consolidates whatever a closing entry lists; ours lists nothing."""

	def test_a_closing_entry_that_lists_a_sale_is_refused(self):
		order = self._paid()
		till = shift_service.selling_till(self.profile)
		invoice = frappe.get_doc("POS Invoice", order.sales_invoice)

		closing = frappe.get_doc(
			{
				"doctype": "POS Closing Entry",
				"pos_opening_entry": till.name,
				"pos_profile": self.profile,
				"user": till.user,
				"company": till.company,
				"period_start_date": till.period_start_date,
				"period_end_date": frappe.utils.now_datetime(),
				"posting_date": frappe.utils.nowdate(),
				"pos_transactions": [
					{
						"pos_invoice": invoice.name,
						"posting_date": invoice.posting_date,
						"grand_total": invoice.grand_total,
						"customer": invoice.customer,
					}
				],
			}
		)

		with self.assertRaises(frappe.ValidationError) as refused:
			closing.insert(ignore_permissions=True)

		self.assertIn("twice", str(refused.exception))

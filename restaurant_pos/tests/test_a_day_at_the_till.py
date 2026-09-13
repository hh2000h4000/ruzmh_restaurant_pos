# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""A whole day at the till, as a cashier — Phase 5's full sale, online.

Every step below has tests of its own. **None walked them one after another as
somebody with no desk rights**, and the two costliest defects of this kind each
passed every test for weeks because the tests ran as Administrator: no real
cashier could refund (`D-144`) or hand a drawer back (`D-157`).

So this runs the real endpoints in the order a cashier meets them — drawer,
order, kitchen, payment, refund, count, end of day — and then asks whether the
day's documents agree with each other: the invoice with the bill, the credit
note with the quote, the drawer with the float plus the sale less the refund,
and the day's report with all of it.

Offline is deliberately absent: it is frozen at one device until the online
system is complete (`D-083`).

Refs: FR-2.1..FR-2.7, FR-8.1..FR-8.3, FR-9.2, BR-042, D-144, D-157, D-188
"""

from unittest.mock import patch

import frappe
from frappe.utils import flt

from restaurant_pos.api import kitchen as kitchen_api
from restaurant_pos.api import order as order_api
from restaurant_pos.api import payment as payment_api
from restaurant_pos.api import returns as returns_api
from restaurant_pos.api import shift as shift_api
from restaurant_pos.tests.test_order import BRANCH, ITEM
from restaurant_pos.tests.test_payment import CASH, PaymentTestBase
from restaurant_pos.tests.test_permissions import SENIOR, _make_user
from restaurant_pos.tests.test_returns import REASON
from restaurant_pos.tests.test_shift import ShiftTestBase

#: The cash the drawer starts the day with.
FLOAT = 200


class TestADayAtTheTill(ShiftTestBase, PaymentTestBase):
	"""`ShiftTestBase` clears the terminal's day and gives it back afterwards;
	`PaymentTestBase` gives it the customer, warehouse and fiscal year an
	invoice needs. Neither is repeated here."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# A senior cashier: the shortest real login that may refund on its own.
		# A plain cashier needs a manager's PIN for that, which is its own rule.
		cls.cashier = _make_user(SENIOR, "POS Senior Cashier")
		cls.grill = frappe.db.get_value(
			"Production Center", {"title": "RPOS Test Grill", "branch": BRANCH}, "name"
		)
		frappe.db.commit()

	def setUp(self):
		super().setUp()
		# The dish goes to the grill by a rule, the way a restaurant sets it up —
		# not by writing the station onto the line, which the endpoint never does.
		frappe.db.delete("POS Printer Routing Rule", {"branch": BRANCH, "item": ITEM})
		frappe.get_doc(
			{
				"doctype": "POS Printer Routing Rule",
				"branch": BRANCH,
				"item": ITEM,
				"production_center": self.grill,
				"priority": 1,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)

		frappe.set_user(self.cashier)
		frappe.local.rpos_permission_cache = {}

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.rpos_permission_cache = {}
		super().tearDown()

	def test_a_day_s_documents_agree_with_each_other(self):
		# Rendering runs in a worker after commit, and a test never commits — so
		# what is checked is that each document **asked** for its paper.
		printed = []
		with patch(
			"restaurant_pos.utils.printing.enqueue_print",
			side_effect=lambda method, **kwargs: printed.append((method, kwargs)),
		):
			# Morning: the drawer, and the day with it (FR-8.1).
			till = shift_api.open_till(pos_profile=self.profile, opening_floats={CASH: FLOAT})

			# A customer: three of the dish, to the grill (FR-2.1..FR-2.4).
			order = order_api.create_order(order_type=self.order_type, pos_profile=self.profile)["order_name"]
			order_api.add_item(order_name=order, item=ITEM, qty=3)
			sent = kitchen_api.send_to_kitchen(order_name=order)

			# Paid in cash (FR-2.7).
			total = flt(frappe.db.get_value("Restaurant Order", order, "total_amount"))
			paid = payment_api.process_payment(order_name=order, payments=[{"method": CASH, "amount": total}])

			# One comes back — quoted first, as the screen does (FR-9.2).
			row = returns_api.get_returnable(order)["items"][0]["row"]
			quoted = returns_api.preview_return(order, [{"row": row, "qty": 1}])["refund_amount"]
			refund = returns_api.create_return(
				order_name=order, items=[{"row": row, "qty": 1}], reason_code=REASON
			)

			# Evening: count the drawer, then end the day (FR-8.2, FR-8.3).
			drawer = shift_api.get_till_summary(till["entry"])
			closed = shift_api.close_till(
				opening_entry=till["entry"], counted={CASH: drawer["till_expected"]}
			)
			shift_api.close_day(shift=till["shift"], pos_profile=self.profile)
			day = shift_api.get_day_summary(till["shift"])

		invoice = frappe.get_doc("Sales Invoice", paid["sales_invoice"])
		credit = frappe.get_doc("Sales Invoice", refund["credit_note"])

		with self.subTest("the kitchen got its ticket, at the station the rule names"):
			self.assertEqual(len(sent["kots_created"]), 1)
			kot = sent["kots_created"][0]["kot_name"]
			self.assertEqual(
				frappe.db.get_value("Kitchen Order Ticket", kot, "production_center"), self.grill
			)

		with self.subTest("the invoice is the bill, filed under who took the money"):
			self.assertEqual(invoice.docstatus, 1)
			self.assertAlmostEqual(flt(invoice.rounded_total or invoice.grand_total), total, places=2)
			self.assertEqual(frappe.db.get_value("Restaurant Order", order, "cashier"), self.cashier)

		with self.subTest("the credit note reverses that sale, by exactly what was quoted"):
			self.assertEqual(
				(credit.docstatus, credit.is_return, credit.return_against), (1, 1, invoice.name)
			)
			self.assertGreater(quoted, 0)
			self.assertAlmostEqual(refund["refund_amount"], quoted, places=2)
			self.assertAlmostEqual(abs(flt(credit.rounded_total or credit.grand_total)), quoted, places=2)
			self.assertEqual(credit.owner, self.cashier)

		with self.subTest("the drawer holds the float, plus the sale, less the refund"):
			self.assertAlmostEqual(drawer["till_expected"], FLOAT + total - quoted, places=2)
			self.assertEqual(closed["settlement"]["variance"], 0)
			self.assertEqual(
				frappe.db.get_value("POS Closing Entry", closed["closing_entry"], "docstatus"), 1
			)
			self.assertEqual(
				frappe.db.get_value("POS Closing Entry", closed["closing_entry"], "owner"), self.cashier
			)

		with self.subTest("the day's report tells the same day"):
			self.assertEqual(frappe.db.get_value("Restaurant Shift", till["shift"], "status"), "closed")
			self.assertAlmostEqual(day["sales"], total, places=2)
			self.assertAlmostEqual(day["returns"], quoted, places=2)
			self.assertEqual(day["orders"]["still_open"], 0)

		with self.subTest("the refund is on the audit log, under the cashier"):
			self.assertTrue(
				frappe.db.exists(
					"POS Audit Log",
					{"restaurant_order": order, "action_type": "return_created", "cashier": self.cashier},
				)
			)

		with self.subTest("each document asked for its paper"):
			self.assertIn(("print_kot", {"kot_name": kot}), printed)
			self.assertIn(("print_receipt", {"invoice_name": invoice.name, "order_name": order}), printed)
			self.assertIn(("print_receipt", {"invoice_name": credit.name, "order_name": order}), printed)

		with self.subTest("every borrowed right was handed back"):
			self.assertEqual(frappe.session.user, self.cashier)

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The least a branch needs to sell: a counter, made by quick setup alone.

No hall, no table, no station, no printer — a café or a supermarket till.
Separating a terminal from its hall (`D-391`..`D-395`) and printing only what
was routed (`D-396`) were both for this branch: none of the screens it does
not use may stand in its way, and nothing may print or ring for it.

So this makes the branch the way an owner would, from the one quick-setup
form, and runs a cashier's day on it through the real endpoints: the terminal
loads, the drawer opens, a sale is sent and paid, a part is refunded, the
drawer is counted and the day closed.

Refs: D-307, D-364, D-395, D-396
"""

import uuid
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from restaurant_pos.api import bell as bell_api
from restaurant_pos.api import kitchen as kitchen_api
from restaurant_pos.api import order as order_api
from restaurant_pos.api import payment as payment_api
from restaurant_pos.api import returns as returns_api
from restaurant_pos.api import session as session_api
from restaurant_pos.api import shift as shift_api
from restaurant_pos.tests.test_order import ITEM, TEST_ITEM_RATE
from restaurant_pos.tests.test_payment import _ensure_fiscal_year
from restaurant_pos.tests.test_permissions import SENIOR, _make_user
from restaurant_pos.tests.test_returns import REASON
from restaurant_pos.utils import quick_setup
from restaurant_pos.utils.invoice_number import BRANCH_NUMBER, DEVICE_NUMBER
from restaurant_pos.utils.sale_doc import SALE

#: The cash the drawer starts the day with.
FLOAT = 100


class ACounterBranchSellsWithNothingElseSetUp(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		_ensure_fiscal_year()
		tag = uuid.uuid4().hex[:6]
		cls.made = quick_setup.run(
			{
				"company": frappe.db.get_value("Company", {}, "name"),
				"branch": f"RPOS Counter {tag}",
				"dine_in": 0,
				"terminal": f"RPOS Counter Till {tag}",
			}
		)
		cls.branch = cls.made["branch"]
		cls.profile = cls.made["pos_profile"]
		profile = frappe.get_doc("POS Profile", cls.profile)
		cls.cash = profile.payments[0].mode_of_payment
		# The dish has a price on the list the till sells from.
		if not frappe.db.exists("Item Price", {"item_code": ITEM, "price_list": profile.selling_price_list}):
			frappe.get_doc(
				{
					"doctype": "Item Price",
					"item_code": ITEM,
					"price_list": profile.selling_price_list,
					"price_list_rate": TEST_ITEM_RATE,
				}
			).insert(ignore_permissions=True)
		cls.order_type = frappe.db.get_value("Restaurant Order Type", {"title": "Takeaway"}, "name")
		cls.cashier = _make_user(SENIOR, "POS Senior Cashier")
		# The manager pairs the machine, as on the first morning (`D-226`).
		code = session_api.issue_device_code(cls.profile)["code"]
		cls.device_token = session_api.pair_device(code, device_name="Counter")["device_token"]

	def setUp(self):
		frappe.set_user(self.cashier)
		frappe.local.rpos_permission_cache = {}

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.rpos_permission_cache = {}

	def test_what_quick_setup_made_is_only_a_branch_and_a_terminal(self):
		frappe.set_user("Administrator")
		self.assertEqual(self.made["sections"], [])
		self.assertEqual(self.made["tables"], 0)
		self.assertFalse(frappe.db.exists("Restaurant Section", {"branch": self.branch}))
		self.assertFalse(frappe.db.exists("Production Center", {"branch": self.branch}))
		self.assertFalse(frappe.db.exists("POS Printer", {"branch": self.branch}))
		profile = frappe.get_doc("POS Profile", self.profile)
		self.assertEqual(profile.rpos_branch, self.branch)
		self.assertFalse(profile.restaurant_section)
		self.assertFalse(profile.default_printer)

	def test_a_cashier_s_day_on_it(self):
		queued = []
		with (
			patch(
				"restaurant_pos.utils.printing.enqueue_print",
				side_effect=lambda method, **kwargs: queued.append(method),
			),
			# Under tests only, ERPNext's closing merges **every** unmerged POS
			# Invoice on the site when the entry lists none — ours always lists
			# none (`D-022`), so in production it merges nothing. Made to do here
			# what it does there.
			patch(
				"erpnext.accounts.doctype.pos_invoice_merge_log.pos_invoice_merge_log.get_all_unconsolidated_invoices",
				return_value=[],
			),
			# And its `finally` commits, merged or not — which here would keep
			# this branch on the test site for every later test to find as «the
			# first terminal». The class's rollback is what cleans up after it.
			patch.object(frappe.db, "commit"),
		):
			# The terminal loads, with no hall to open on.
			session = session_api.load_pos_session(pos_profile=self.profile, device_token=self.device_token)

			till = shift_api.open_till(pos_profile=self.profile, opening_floats={self.cash: FLOAT})

			order = order_api.create_order(order_type=self.order_type, pos_profile=self.profile)["order_name"]
			order_api.add_item(order_name=order, item=ITEM, qty=2)
			sent = kitchen_api.send_to_kitchen(order_name=order)

			total = flt(frappe.db.get_value("Restaurant Order", order, "total_amount"))
			paid = payment_api.process_payment(
				order_name=order, payments=[{"method": self.cash, "amount": total}]
			)

			row = returns_api.get_returnable(order)["items"][0]["row"]
			refund = returns_api.create_return(
				order_name=order, items=[{"row": row, "qty": 1}], reason_code=REASON
			)

			drawer = shift_api.get_till_summary(till["entry"])
			closed = shift_api.close_till(
				opening_entry=till["entry"], counted={self.cash: drawer["till_expected"]}
			)
			shift_api.close_day(shift=till["shift"], pos_profile=self.profile)
			bell = bell_api.get_bell(pos_profile=self.profile)

		with self.subTest("the terminal loads with no hall"):
			self.assertIsNone(session["restaurant_section"])
			self.assertEqual(session["sections"], [])
			self.assertTrue(any(item["item_code"] == ITEM for item in session["items"]))

		with self.subTest("the order is in the branch, in no hall"):
			doc = frappe.db.get_value(
				"Restaurant Order", order, ["branch", "section", "status"], as_dict=True
			)
			self.assertEqual(doc.branch, self.branch)
			self.assertFalse(doc.section)
			self.assertEqual(doc.status, "closed")

		with self.subTest("sending made no ticket: there is no station"):
			self.assertEqual(sent["kots_created"], [])
			self.assertFalse(frappe.db.exists("Kitchen Order Ticket", {"restaurant_order": order}))

		with self.subTest("the invoice is numbered in the branch, from the terminal"):
			invoice = frappe.get_doc(SALE, paid["sales_invoice"])
			self.assertEqual(invoice.docstatus, 1)
			prefix = "{}-{}-".format(
				frappe.db.get_value("Branch", self.branch, BRANCH_NUMBER),
				frappe.db.get_value("POS Profile", self.profile, DEVICE_NUMBER),
			)
			self.assertTrue(invoice.name.startswith(prefix), invoice.name)
			self.assertAlmostEqual(flt(invoice.rounded_total or invoice.grand_total), total, places=2)
			self.assertEqual(
				invoice.items[0].warehouse, frappe.db.get_value("Branch", self.branch, "default_warehouse")
			)

		with self.subTest("the refund is a credit note against it"):
			credit = frappe.get_doc(SALE, refund["credit_note"])
			self.assertEqual((credit.docstatus, credit.return_against), (1, invoice.name))

		with self.subTest("the drawer and the day close"):
			self.assertAlmostEqual(drawer["till_expected"], FLOAT + total - refund["refund_amount"], places=2)
			self.assertEqual(closed["settlement"]["variance"], 0)
			self.assertEqual(frappe.db.get_value("Restaurant Shift", till["shift"], "status"), "closed")

		with self.subTest("nothing was sent to paper, and nothing rings"):
			self.assertEqual(queued, [])
			self.assertEqual(bell["items"], [])

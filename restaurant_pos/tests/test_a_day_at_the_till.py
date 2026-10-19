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
from restaurant_pos.api import permissions as permissions_api
from restaurant_pos.api import returns as returns_api
from restaurant_pos.api import shift as shift_api
from restaurant_pos.setup.defaults import create_default_data
from restaurant_pos.tests.test_discount_override import _user as _user_with_pin
from restaurant_pos.tests.test_loyalty import LoyaltyTestBase
from restaurant_pos.tests.test_order import BRANCH, ITEM, free_table
from restaurant_pos.tests.test_payment import CASH, PaymentTestBase
from restaurant_pos.tests.test_permissions import CASHIER, SENIOR, _make_user
from restaurant_pos.tests.test_returns import REASON
from restaurant_pos.tests.test_shift import ShiftTestBase
from restaurant_pos.utils import loyalty, totals
from restaurant_pos.utils import shift as shift_service
from restaurant_pos.utils.sale_doc import SALE

#: The manager who approves the evening's discount, and the PIN they type.
DINNER_MANAGER = "rpos_dinner_manager@example.com"
DINNER_MANAGER_PIN = "58214"

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
		# And a colleague who covers the till while the first steps away (`D-218`).
		cls.covering = _make_user(CASHIER, "POS Cashier")
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
		with (
			patch(
				"restaurant_pos.utils.printing.enqueue_print",
				side_effect=lambda method, **kwargs: printed.append((method, kwargs)),
			),
			# The terminal and the kitchen have printers: a job is asked for only
			# where there is paper (`D-364`).
			patch("restaurant_pos.utils.printing.receipt_printer", return_value="RPOS Test Printer"),
			patch("restaurant_pos.utils.printing.kot_printer", return_value="RPOS Test Printer"),
			patch("restaurant_pos.utils.printing._cashier_printer", return_value="RPOS Test Printer"),
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

		invoice = frappe.get_doc(SALE, paid["sales_invoice"])
		credit = frappe.get_doc(SALE, refund["credit_note"])

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

	def _as(self, user: str) -> None:
		frappe.set_user(user)
		frappe.local.rpos_permission_cache = {}

	def _sold(self, qty: int) -> float:
		"""A takeaway rung up and paid in cash through the real endpoints; its total."""
		order = order_api.create_order(order_type=self.order_type, pos_profile=self.profile)["order_name"]
		order_api.add_item(order_name=order, item=ITEM, qty=qty)
		total = flt(frappe.db.get_value("Restaurant Order", order, "total_amount"))
		payment_api.process_payment(order_name=order, payments=[{"method": CASH, "amount": total}])
		return total

	def test_a_shared_drawer_s_day_counts_both_cashiers_and_prints_its_reports(self):
		"""`D-217`..`D-219` — the day as the user's customers run a shared till.

		The cashier opens the drawer, sells, prints an X report before stepping
		away; a colleague signs in and sells into **the same drawer**, as Vitec
		does; the first comes back, counts and closes, and ends the day. Then the
		documents must agree: the drawer holds both cashiers' takings, the reports
		say who took what, and a Z came out at each close.

		**The branch is made shared through the profile the till reads**, not by
		writing it: closing a drawer commits, and a setting written before that
		outlived its test once already (`D-219`).
		"""
		read_profile = shift_service._profile

		def shared(pos_profile):
			profile = read_profile(pos_profile)
			profile.branch_shift_type = "single"
			return profile

		printed = []
		with (
			patch(
				"restaurant_pos.utils.printing.enqueue_print",
				side_effect=lambda method, **kwargs: printed.append((method, kwargs)),
			),
			patch.object(shift_service, "_profile", side_effect=shared),
			# The terminal has a printer — said here rather than written onto the
			# profile, for the same reason as the branch above.
			patch("restaurant_pos.utils.printing.receipt_printer", return_value="RPOS Test Printer"),
			patch("restaurant_pos.utils.printing._cashier_printer", return_value="RPOS Test Printer"),
		):
			till = shift_api.open_till(pos_profile=self.profile, opening_floats={CASH: FLOAT})
			first = self._sold(3)
			# Before stepping away: what is in the drawer now, on paper.
			shift_api.print_till_report(till["entry"])

			# A colleague covers, on their own login, into the same drawer.
			self._as(self.covering)
			joined = shift_api.open_till(pos_profile=self.profile)
			second = self._sold(1)

			# The first comes back, counts, closes, and ends the day.
			self._as(self.cashier)
			drawer = shift_api.get_till_summary(till["entry"])
			closed = shift_api.close_till(
				opening_entry=till["entry"], counted={CASH: drawer["till_expected"]}
			)
			shift_api.close_day(shift=till["shift"], pos_profile=self.profile)
			day = shift_api.get_day_summary(till["shift"])

		def takings(report):
			return {row["user"]: row["sales"] for row in report["by_cashier"]}

		with self.subTest("the colleague joined the open drawer rather than opening another"):
			self.assertTrue(joined["joined"])
			self.assertEqual(joined["entry"], till["entry"])

		with self.subTest("the drawer holds the float and both cashiers' takings"):
			self.assertAlmostEqual(drawer["till_expected"], FLOAT + first + second, places=2)
			self.assertEqual(closed["settlement"]["variance"], 0)

		with self.subTest("the drawer's report says who took what"):
			self.assertEqual(takings(drawer), {self.cashier: first, self.covering: second})

		with self.subTest("the day's report tells the same day, and lists the drawer it counted"):
			self.assertAlmostEqual(day["sales"], first + second, places=2)
			self.assertEqual(takings(day), {self.cashier: first, self.covering: second})
			(counted,) = day["tills"]
			self.assertAlmostEqual(counted["difference"], 0, places=2)
			self.assertAlmostEqual(sum(row["gross"] for row in day["taxes"]), first + second, places=2)

		with self.subTest("an X report before stepping away, a Z at each close"):
			drawer_reports = [kw for method, kw in printed if kw.get("opening_entry") == till["entry"]]
			self.assertEqual(len(drawer_reports), 2, "X on the button, Z at the close")
			self.assertIn(
				("print_shift_report", {"pos_profile": self.profile, "shift": till["shift"]}), printed
			)


class TestADinnerService(ShiftTestBase, LoyaltyTestBase):
	"""An evening where the money is hardest: a table, a manager's discount, points spent.

	Each piece has tests of its own (`BR-031`, `D-189`); none walked them in one
	day through the endpoints, as a cashier, and then asked whether the drawer,
	the day's report and the guest's balance still agree. That is where money
	logic goes wrong — two correct rules that do not add up.

	`LoyaltyTestBase` brings the programme and the Saudi VAT on the terminal, so
	the tax claims below are not `0 == 0`; `ShiftTestBase` the clean day.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# The discount ceilings live in the shipped permission sets (08 §3): a
		# senior cashier may give 10%, a manager 50%.
		create_default_data()
		cls.cashier = _make_user(SENIOR, "POS Senior Cashier")
		cls.manager = _user_with_pin(DINNER_MANAGER, "POS Manager", DINNER_MANAGER_PIN)
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.rpos_permission_cache = {}
		super().tearDown()

	def _as(self, user: str) -> None:
		frappe.set_user(user)
		frappe.local.rpos_permission_cache = {}

	def test_a_dinner_service_s_money_agrees_with_itself(self):
		# Set up at the desk, before the cashier arrives: a regular with points,
		# and a free table.
		guest = self._guest()
		self._give(guest, 300)
		table = frappe.db.get_value("Restaurant Table", {"section": self.section, "is_active": 1}, "name")
		free_table(table)

		self._as(self.cashier)
		with patch("restaurant_pos.utils.printing.enqueue_print"):
			till = shift_api.open_till(pos_profile=self.profile, opening_floats={CASH: FLOAT})

			# A table of two, sent to the kitchen, and a discount beyond the
			# cashier's own ceiling — approved by a manager's PIN (BR-031).
			dinner = order_api.create_order(
				order_type=self.dine_in, pos_profile=self.profile, table=table, cover_count=2
			)["order_name"]
			order_api.add_item(order_name=dinner, item=ITEM, qty=4)
			kitchen_api.send_to_kitchen(order_name=dinner)
			approval = permissions_api.validate_discount_override(
				pin=DINNER_MANAGER_PIN,
				percentage=40,
				reason="RPOS test: a long wait",
				branch=BRANCH,
				pos_profile=self.profile,
				order_name=dinner,
			)
			due = payment_api.preview_totals(dinner, "percentage", 40)["total_amount"]
			half = totals.money(due / 2)
			# Paid in two parts, as a table of two splits it.
			payment_api.process_payment(
				order_name=dinner,
				payments=[
					{"method": CASH, "amount": half},
					{"method": CASH, "amount": totals.money(due - half)},
				],
				discount_type="percentage",
				discount_value=40,
				manager_override_token=approval["override_token"],
			)

			# A regular spends points on a takeaway (D-189).
			regular = order_api.create_order(
				order_type=self.order_type, pos_profile=self.profile, customer=guest
			)["order_name"]
			order_api.add_item(order_name=regular, item=ITEM, qty=4)
			owed = payment_api.preview_totals(regular, loyalty_points=100)["total_amount"]
			payment_api.process_payment(
				order_name=regular, payments=[{"method": CASH, "amount": owed}], loyalty_points_redeemed=100
			)

			drawer = shift_api.get_till_summary(till["entry"])
			closed = shift_api.close_till(
				opening_entry=till["entry"], counted={CASH: drawer["till_expected"]}
			)
			shift_api.close_day(shift=till["shift"], pos_profile=self.profile)
			day = shift_api.get_day_summary(till["shift"])

		self._as("Administrator")
		dinner_doc = frappe.get_doc("Restaurant Order", dinner)
		regular_doc = frappe.get_doc("Restaurant Order", regular)

		with self.subTest("the table's discount went through, named to the manager who approved it"):
			self.assertEqual(dinner_doc.status, "closed")
			self.assertEqual(dinner_doc.discount_approved_by, self.manager)
			self.assertGreater(flt(dinner_doc.discount_amount), 0)
			self.assertAlmostEqual(flt(dinner_doc.total_amount), due, places=2)

		with self.subTest("the table's two payments are both on its invoice"):
			invoice = frappe.get_doc(SALE, dinner_doc.sales_invoice)
			self.assertEqual(len(invoice.payments), 2)
			self.assertAlmostEqual(sum(flt(row.amount) for row in invoice.payments), due, places=2)

		with self.subTest("the points came off the bill, and off the guest's balance"):
			self.assertAlmostEqual(flt(regular_doc.total_amount), owed, places=2)
			earned = int(regular_doc.loyalty_points_earned or 0)
			self.assertEqual(loyalty.balance(guest, self.program), 300 - 100 + earned)

		with self.subTest("the drawer holds the float and exactly what both bills came to"):
			self.assertAlmostEqual(drawer["till_expected"], FLOAT + due + owed, places=2)
			self.assertEqual(closed["settlement"]["variance"], 0)

		with self.subTest("the day's report tells the same evening"):
			self.assertAlmostEqual(day["sales"], due + owed, places=2)
			self.assertGreaterEqual(day["discounts"], flt(dinner_doc.discount_amount))
			self.assertAlmostEqual(day["gross_sales"], day["sales"] + day["discounts"], places=2)
			# VAT is on: the tax table carries real tax, and adds up to the takings.
			self.assertGreater(sum(row["tax"] for row in day["taxes"]), 0)
			self.assertAlmostEqual(sum(row["gross"] for row in day["taxes"]), due + owed, places=2)

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Loyalty points: earned on a paid bill, spent as a discount, followed on a return.

Every test drives the real payment and the real return. Loyalty is money the
restaurant owes, so the claims are made on the ledger ERPNext keeps
(`Loyalty Point Entry`) and on the invoice ZATCA reads — not on a figure the
module reports about itself.

Refs: BR-080..BR-084, FR-10.5, D-189, D-190
"""

import math

import frappe
from frappe.utils import add_days, flt, getdate, today

from restaurant_pos.tests.test_order import ITEM
from restaurant_pos.tests.test_payment import CASH, PaymentTestBase
from restaurant_pos.utils import loyalty, returns, totals
from restaurant_pos.utils import order as orders
from restaurant_pos.utils import payment as service

PROGRAM = "RPOS Test Loyalty"
LEDGER = "Loyalty Point Entry"
REASON = "goods_returned"

#: The numbers the user approved for the restaurant (`D-189`): a point per riyal,
#: a hundred points worth five riyals, spend from a hundred, at most half a bill.
EARN_PER_POINT = 1
POINT_VALUE = 0.05
MINIMUM = 100
MOST_OF_A_BILL = 50
DAYS = 365


def _ensure_program(company: str) -> str:
	values = {
		"loyalty_program_type": "Single Tier Program",
		"from_date": "2020-01-01",
		"to_date": None,
		"auto_opt_in": 0,
		"customer_group": None,
		"customer_territory": None,
		"conversion_factor": POINT_VALUE,
		"expiry_duration": DAYS,
		"company": company,
		"rpos_min_redeem_points": MINIMUM,
		"rpos_max_redeem_percent": MOST_OF_A_BILL,
	}
	rule = {"tier_name": "Guest", "min_spent": 0, "collection_factor": EARN_PER_POINT}

	name = frappe.db.get_value("Loyalty Program", {"loyalty_program_name": PROGRAM}, "name")
	if name:
		program = frappe.get_doc("Loyalty Program", name)
		program.update(values)
		program.set("collection_rules", [rule])
		program.save(ignore_permissions=True)
		return program.name

	return (
		frappe.get_doc(
			{
				"doctype": "Loyalty Program",
				"loyalty_program_name": PROGRAM,
				"collection_rules": [rule],
				**values,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


class LoyaltyTestBase(PaymentTestBase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_value("POS Profile", cls.profile, "company")
		cls.program = _ensure_program(cls.company)

		frappe.db.set_value("Restaurant Order Type", cls.order_type, "allows_loyalty", 1)
		frappe.clear_document_cache("Restaurant Order Type", cls.order_type)

		# **With the Saudi VAT on**, VAT-inclusive as the menus are (`D-091`).
		#
		# The test terminal carries no tax template, and without one every claim
		# below about tax was `0 == 0`: a mutation earning the points on the
		# VAT-inclusive total survived, because the two totals were the same
		# figure. The demo's own builder, so there is one 15% template in the
		# code and not a second one here; and not the site's default, so the
		# modules that run after this one see the terminal they always saw.
		from restaurant_pos.setup import demo

		cls.original_taxes = frappe.db.get_value("POS Profile", cls.profile, "taxes_and_charges")
		cls.original_tax_id = frappe.db.get_value("Company", cls.company, "tax_id")
		template = demo._vat_template(frappe._dict(name=cls.profile, company=cls.company))
		frappe.db.set_value("Sales Taxes and Charges Template", template, "is_default", 0)
		frappe.clear_document_cache("POS Profile", cls.profile)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()

		# Given back after the class's own work is rolled back, and committed,
		# because the change above was.
		frappe.db.set_value("POS Profile", cls.profile, "taxes_and_charges", cls.original_taxes)
		frappe.db.set_value("Company", cls.company, "tax_id", cls.original_tax_id)
		frappe.clear_document_cache("POS Profile", cls.profile)
		frappe.db.commit()

	def _guest(self, enrolled: bool = True) -> str:
		"""A new person for every test, so no test reads another's balance."""
		return (
			frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": f"RPOS Loyalty {frappe.generate_hash(length=8)}",
					"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
					"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
					"loyalty_program": self.program if enrolled else None,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _give(self, customer: str, points: int, days: int = DAYS) -> str:
		"""A grant with no bill behind it — the shape a manager's adjustment takes."""
		return (
			frappe.get_doc(
				{
					"doctype": LEDGER,
					"company": self.company,
					"loyalty_program": self.program,
					"customer": customer,
					"loyalty_points": points,
					"purchase_amount": 0,
					"expiry_date": add_days(today(), days),
					"posting_date": today(),
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _bill(self, customer: str | None, qty: int = 1, **kwargs):
		order = self._order(customer=customer, **kwargs)
		orders.add_item(order, item=ITEM, qty=qty)
		order.reload()
		return order

	def _settle(self, order, points: int = 0) -> dict:
		"""Pay the bill exactly, at the figure it comes to once the points are off."""
		order.loyalty_points = points
		totals.calculate(order)
		result = service.process_payment(
			order, payments=[{"method": CASH, "amount": order.total_amount}], loyalty_points=points
		)
		order.reload()
		return result

	def _balance(self, customer: str) -> int:
		return loyalty.balance(customer, self.program)

	def _invoice(self, order):
		return frappe.get_doc("Sales Invoice", order.sales_invoice)

	def _return(self, order, qty: int) -> dict:
		row = returns.returnable(order)["items"][0]["row"]
		return returns.create_return(order, items=[{"row": row, "qty": qty}], reason_code=REASON)


class TestEarning(LoyaltyTestBase):
	def test_a_paid_bill_earns_on_its_net_total_before_vat(self):
		"""BR-081 — and never on the tax, as Starbucks Saudi says in its terms."""
		guest = self._guest()
		order = self._bill(guest, qty=4)

		result = self._settle(order)

		invoice = self._invoice(order)
		# Without tax the net and the grand total are one figure, and this test
		# would pass whichever one the points were earned on.
		self.assertLess(flt(invoice.net_total), flt(invoice.grand_total), "the bill must carry VAT")
		expected = math.floor(flt(invoice.net_total) / EARN_PER_POINT)
		self.assertGreater(expected, 0)
		self.assertEqual(result["loyalty_points_earned"], expected)
		self.assertEqual(order.loyalty_points_earned, expected)
		self.assertEqual(self._balance(guest), expected)

		grant = frappe.get_doc(LEDGER, {"invoice": invoice.name, "loyalty_points": (">", 0)})
		self.assertAlmostEqual(flt(grant.purchase_amount), flt(invoice.net_total), places=2)

	def test_the_points_last_as_long_as_the_program_says(self):
		guest = self._guest()
		order = self._bill(guest)
		self._settle(order)

		grant = frappe.get_doc(LEDGER, {"invoice": order.sales_invoice})
		self.assertEqual(getdate(grant.expiry_date), getdate(add_days(grant.posting_date, DAYS)))

	def test_the_terminals_own_customer_earns_nothing(self):
		"""Every anonymous bill is filed under it; it must not collect their points."""
		walk_in = frappe.db.get_value("POS Profile", self.profile, "customer")
		frappe.db.set_value("Customer", walk_in, "loyalty_program", self.program)

		order = self._bill(walk_in)
		result = self._settle(order)

		self.assertFalse(frappe.db.exists(LEDGER, {"invoice": order.sales_invoice}))
		self.assertNotIn("loyalty_points_earned", result)

	def test_a_bill_with_no_customer_earns_nothing(self):
		order = self._bill(None)
		self._settle(order)

		self.assertFalse(frappe.db.exists(LEDGER, {"invoice": order.sales_invoice}))

	def test_an_order_type_with_loyalty_off_earns_nothing(self):
		"""A delivery platform's guest is the platform's customer."""
		guest = self._guest()
		order = self._bill(guest)
		frappe.db.set_value("Restaurant Order Type", self.order_type, "allows_loyalty", 0)
		frappe.clear_document_cache("Restaurant Order Type", self.order_type)

		try:
			self._settle(order)
		finally:
			frappe.db.set_value("Restaurant Order Type", self.order_type, "allows_loyalty", 1)
			frappe.clear_document_cache("Restaurant Order Type", self.order_type)

		self.assertFalse(frappe.db.exists(LEDGER, {"invoice": order.sales_invoice}))

	def test_an_account_order_earns_nothing_whatever_its_switch_says(self):
		"""A platform's guest or a company billed monthly is somebody else's debt
		(`D-038`). The switch is left on, as the migrate left it on every type."""
		guest = self._guest()
		order = self._bill(guest)
		frappe.db.set_value("Restaurant Order Type", self.order_type, "counterparty", "account")
		frappe.clear_document_cache("Restaurant Order Type", self.order_type)

		try:
			self._settle(order)
		finally:
			frappe.db.set_value("Restaurant Order Type", self.order_type, "counterparty", "walk_in")
			frappe.clear_document_cache("Restaurant Order Type", self.order_type)

		self.assertFalse(frappe.db.exists(LEDGER, {"invoice": order.sales_invoice}))

	def test_a_customer_in_no_program_earns_nothing(self):
		guest = self._guest(enrolled=False)
		order = self._bill(guest)
		self._settle(order)

		self.assertFalse(frappe.db.exists(LEDGER, {"invoice": order.sales_invoice}))

	def test_a_program_that_opts_customers_in_enrols_them_on_their_first_sale(self):
		"""ERPNext enrols on saving the customer; a regular made before the program
		existed would otherwise earn nothing until somebody edited them."""
		guest = self._guest(enrolled=False)
		frappe.db.set_value("Loyalty Program", self.program, "auto_opt_in", 1)
		frappe.clear_document_cache("Loyalty Program", self.program)

		try:
			order = self._bill(guest)
			self._settle(order)
		finally:
			frappe.db.set_value("Loyalty Program", self.program, "auto_opt_in", 0)
			frappe.clear_document_cache("Loyalty Program", self.program)

		self.assertEqual(frappe.db.get_value("Customer", guest, "loyalty_program"), self.program)
		self.assertGreater(self._balance(guest), 0)


class TestSpending(LoyaltyTestBase):
	def test_points_come_off_before_vat_like_any_discount(self):
		"""ZATCA treats a shop's own points as a discount: VAT on what is left.

		ERPNext books them as a payment and charges VAT on the full price. The
		same bill paid twice, once with points, has to carry less tax by exactly
		the tax on what the points took off.
		"""
		plain = self._bill(self._guest(), qty=8)
		self._settle(plain)

		guest = self._guest()
		self._give(guest, 400)
		spent = self._bill(guest, qty=8)
		self._settle(spent, points=200)

		self.assertAlmostEqual(flt(spent.loyalty_amount), 200 * POINT_VALUE, places=2)

		rate = totals.tax_rate_for(self.profile)
		self.assertGreater(rate, 0, "with no VAT the claim below is 0 == 0")
		off = 200 * POINT_VALUE
		drop = off * rate / (100 + rate) if totals.tax_is_inclusive(self.profile) else off * rate / 100

		with_points = self._invoice(spent)
		without = self._invoice(plain)
		self.assertAlmostEqual(
			flt(without.total_taxes_and_charges) - flt(with_points.total_taxes_and_charges), drop, delta=0.02
		)
		self.assertAlmostEqual(flt(with_points.discount_amount), flt(without.discount_amount) + off, places=2)

	def test_the_points_leave_the_balance_and_earn_nothing_themselves(self):
		"""BR-084 — the part the points paid for earns no points."""
		guest = self._guest()
		self._give(guest, 400)
		order = self._bill(guest, qty=8)

		result = self._settle(order, points=200)

		earned = math.floor(flt(self._invoice(order).net_total) / EARN_PER_POINT)
		self.assertEqual(result["loyalty_points_earned"], earned)
		self.assertEqual(self._balance(guest), 400 - 200 + earned)
		self.assertEqual(result["loyalty_balance"], 400 - 200 + earned)

	def test_more_than_the_balance_is_refused_and_nothing_moves(self):
		guest = self._guest()
		self._give(guest, 150)
		order = self._bill(guest, qty=8)

		with self.assertRaises(frappe.ValidationError):
			self._settle(order, points=200)

		self.assertEqual(self._balance(guest), 150)
		self.assertFalse(frappe.db.get_value("Restaurant Order", order.name, "sales_invoice"))

	def test_below_the_minimum_nothing_can_be_spent(self):
		guest = self._guest()
		self._give(guest, MINIMUM - 1)
		order = self._bill(guest, qty=8)

		with self.assertRaises(frappe.ValidationError):
			self._settle(order, points=50)

	def test_more_than_the_programs_share_of_the_bill_is_refused(self):
		"""Half of 25.00 is 12.50, which is 250 points and not one more."""
		guest = self._guest()
		self._give(guest, 1000)

		with self.assertRaises(frappe.ValidationError):
			self._settle(self._bill(guest), points=251)

		self._settle(self._bill(guest), points=250)

	def test_the_screen_is_told_exactly_the_most_it_may_spend(self):
		"""D-125 — the button offers what the server will accept, no more."""
		guest = self._guest()
		self._give(guest, 1000)
		order = self._bill(guest)

		offer = loyalty.on_the_bill(order)["loyalty"]

		self.assertEqual(offer["balance"], 1000)
		self.assertEqual(offer["max_points"], 250)
		self.assertAlmostEqual(offer["max_amount"], 250 * POINT_VALUE, places=2)
		self.assertAlmostEqual(offer["worth"], 1000 * POINT_VALUE, places=2)

	def test_a_walk_in_cannot_spend(self):
		with self.assertRaises(frappe.ValidationError):
			self._settle(self._bill(None), points=100)

	def test_spending_takes_the_points_that_expire_soonest_first(self):
		guest = self._guest()
		later = self._give(guest, 300, days=300)
		sooner = self._give(guest, 100, days=10)
		order = self._bill(guest, qty=8)

		self._settle(order, points=150)

		taken = {
			row.redeem_against: row.loyalty_points
			for row in frappe.get_all(
				LEDGER,
				filters={"invoice": order.sales_invoice, "loyalty_points": ("<", 0)},
				fields=["redeem_against", "loyalty_points"],
			)
		}
		self.assertEqual(taken, {sooner: -100, later: -50})

	def test_expired_points_cannot_be_spent(self):
		guest = self._guest()
		self._give(guest, 500, days=-1)

		self.assertEqual(self._balance(guest), 0)
		with self.assertRaises(frappe.ValidationError):
			self._settle(self._bill(guest, qty=8), points=100)

	def test_a_redemption_is_in_the_audit_log_and_on_the_bills_story(self):
		"""Anything that happens to a bill is written on it — and spending a
		guest's balance is the one loyalty act a cashier can abuse."""
		guest = self._guest()
		self._give(guest, 400)
		order = self._bill(guest, qty=8)

		self._settle(order, points=200)

		audit = frappe.get_all(
			"POS Audit Log",
			filters={"restaurant_order": order.name, "action_type": "loyalty_redeemed"},
			pluck="name",
		)
		self.assertEqual(len(audit), 1)

		story = set(
			frappe.get_all("POS Order Activity", filters={"restaurant_order": order.name}, pluck="action")
		)
		self.assertIn("loyalty_redeemed", story)
		self.assertIn("loyalty_earned", story)

	def test_the_balance_is_read_under_a_lock_on_the_customer(self):
		"""Two tills spending one balance at the same moment is the double spend.

		One thread cannot race itself, so this pins what the race depends on: the
		customer row is locked before the balance is read, and the second till
		waits for the first to commit or roll back.
		"""
		from unittest.mock import patch

		guest = self._guest()
		self._give(guest, 400)
		order = self._bill(guest, qty=8)

		with patch.object(frappe.db, "get_value", side_effect=frappe.db.get_value) as spy:
			self._settle(order, points=200)

		locked = [
			call
			for call in spy.call_args_list
			if call.args[:2] == ("Customer", guest) and call.kwargs.get("for_update")
		]
		self.assertTrue(locked, "the balance was read without locking the customer")

	def test_the_invoice_names_the_points(self):
		guest = self._guest()
		self._give(guest, 400)
		order = self._bill(guest, qty=8)

		self._settle(order, points=200)

		self.assertIn("200", self._invoice(order).remarks)


class TestReturns(LoyaltyTestBase):
	def test_a_full_return_puts_the_balance_back_where_it_was(self):
		guest = self._guest()
		self._give(guest, 400)
		order = self._bill(guest, qty=8)
		self._settle(order, points=200)

		self._return(order, qty=8)

		self.assertEqual(self._balance(guest), 400)

	def test_half_the_bill_back_moves_half_the_points(self):
		guest = self._guest()
		self._give(guest, 400)
		order = self._bill(guest, qty=2)
		earned = self._settle(order, points=100)["loyalty_points_earned"]

		result = self._return(order, qty=1)

		kept = math.floor(earned / 2)
		self.assertEqual(result["loyalty_points_clawed_back"], earned - kept)
		self.assertEqual(result["loyalty_points_restored"], 50)
		self.assertEqual(self._balance(guest), 400 - 100 + kept + 50)

	def test_a_bill_returned_in_two_parts_ends_where_one_return_would(self):
		"""Worked cumulatively, so rounding cannot pile up across parts."""
		guest = self._guest()
		self._give(guest, 400)
		order = self._bill(guest, qty=2)
		self._settle(order, points=100)

		self._return(order, qty=1)
		self._return(order, qty=1)

		self.assertEqual(self._balance(guest), 400)

	def test_a_return_still_refunds_when_its_points_were_spent_since(self):
		"""ERPNext refuses this return outright. Here the balance goes negative and
		the next purchases pay the debt — the refund is never held hostage."""
		guest = self._guest()
		first = self._bill(guest, qty=8)
		earned = self._settle(first)["loyalty_points_earned"]
		self.assertGreaterEqual(earned, MINIMUM)

		second = self._bill(guest, qty=8)
		then = self._settle(second, points=earned)["loyalty_points_earned"]

		result = self._return(first, qty=8)

		self.assertTrue(result["credit_note"])
		self.assertEqual(result["loyalty_points_clawed_back"], earned)
		self.assertEqual(self._balance(guest), then - earned)
		self.assertLess(self._balance(guest), 0)

	def test_a_bill_that_earned_and_spent_nothing_returns_without_touching_points(self):
		order = self._bill(None, qty=2)
		self._settle(order)

		result = self._return(order, qty=1)

		self.assertNotIn("loyalty_points_clawed_back", result)
		self.assertNotIn("loyalty_points_restored", result)


class TestTheReceipt(LoyaltyTestBase):
	"""The receipt is the one thing the guest takes home (`D-189`)."""

	def _context(self, invoice, order):
		from restaurant_pos.utils import printing

		return printing.receipt_context(invoice, printing._receipt_order(order.name))

	def test_it_prints_the_points_spent_earned_and_left(self):
		from restaurant_pos.utils import printing

		guest = self._guest()
		self._give(guest, 400)
		order = self._bill(guest, qty=8)
		self._settle(order, points=200)

		context = self._context(self._invoice(order), order)

		self.assertEqual(context["loyalty"]["spent"], 200)
		self.assertAlmostEqual(context["loyalty"]["amount"], 200 * POINT_VALUE, places=2)
		self.assertEqual(context["loyalty"]["earned"], order.loyalty_points_earned)
		self.assertEqual(context["loyalty"]["balance"], self._balance(guest))

		# Rendered through the shipped template, so a Jinja slip in the new block
		# is a failing test here rather than every receipt in the building.
		template = printing.resolve_template("customer_receipt", paper_width="80mm", branch=order.branch)
		html = printing.render_html(template, context)
		self.assertIn("نقاط الولاء", html)
		self.assertIn("رصيد النقاط", html)

	def test_a_refund_prints_no_points_block(self):
		"""A credit note carrying the sale's points would tell the guest they
		earned something on a refund."""
		guest = self._guest()
		self._give(guest, 400)
		order = self._bill(guest, qty=8)
		self._settle(order, points=200)

		credit = frappe.get_doc("Sales Invoice", self._return(order, qty=8)["credit_note"])

		self.assertIsNone(self._context(credit, order)["loyalty"])

	def test_a_bill_outside_the_scheme_prints_none(self):
		order = self._bill(None)
		self._settle(order)

		self.assertIsNone(self._context(self._invoice(order), order)["loyalty"])


class TestTheProgram(LoyaltyTestBase):
	def _draft(self, **changes):
		doc = frappe.get_doc(
			{
				"doctype": "Loyalty Program",
				"loyalty_program_name": f"RPOS Refused {frappe.generate_hash(length=6)}",
				"loyalty_program_type": "Single Tier Program",
				"from_date": "2020-01-01",
				"conversion_factor": POINT_VALUE,
				"expiry_duration": DAYS,
				"company": self.company,
				"rpos_min_redeem_points": MINIMUM,
				"rpos_max_redeem_percent": MOST_OF_A_BILL,
				"collection_rules": [{"tier_name": "Guest", "min_spent": 0, "collection_factor": 1}],
			}
		)
		doc.update(changes)
		return doc

	def test_tiers_are_refused(self):
		"""ERPNext's tier function puts a guest a tier too high — measured."""
		doc = self._draft(loyalty_program_type="Multiple Tier Program")
		doc.append("collection_rules", {"tier_name": "Gold", "min_spent": 1000, "collection_factor": 1})

		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_an_empty_expiry_is_refused(self):
		"""ERPNext would stamp every grant with today's date as its expiry."""
		with self.assertRaises(frappe.ValidationError):
			self._draft(expiry_duration=0).insert(ignore_permissions=True)

	def test_a_share_of_the_bill_above_everything_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._draft(rpos_max_redeem_percent=150).insert(ignore_permissions=True)

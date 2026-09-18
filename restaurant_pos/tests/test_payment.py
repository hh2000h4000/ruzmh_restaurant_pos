# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Payment and Sales Invoice tests.

Refs: BR-016, BR-020..BR-024, FR-2.7, FR-10.2, FR-10.3, FR-10.4
"""

import uuid

import frappe
from frappe.utils import add_to_date, flt, getdate, now_datetime

from restaurant_pos.api import payment as api
from restaurant_pos.tests.test_order import ITEM, OrderTestBase, _make_cashier, free_table
from restaurant_pos.utils import order as orders
from restaurant_pos.utils import payment as service
from restaurant_pos.utils import totals

CASH = "Cash"


def _ensure_fiscal_year() -> None:
	"""A Sales Invoice cannot post without one.

	Like the price list and the warehouse types, Fiscal Year comes from the
	ERPNext setup wizard, which this site never ran (D-012).
	"""
	today = getdate()
	if frappe.db.exists(
		"Fiscal Year",
		{"year_start_date": ("<=", today), "year_end_date": (">=", today), "disabled": 0},
	):
		return

	frappe.get_doc(
		{
			"doctype": "Fiscal Year",
			"year": str(today.year),
			"year_start_date": f"{today.year}-01-01",
			"year_end_date": f"{today.year}-12-31",
		}
	).insert(ignore_permissions=True)


class TestAPosInvoiceIsNotCancelled(OrderTestBase):
	"""D-063 — a POS sale is reversed by a return, never by a cancellation.

	Cancelling from the ERPNext desk reversed the ledger and left the order still
	saying `closed`, with nothing told (D-062). Making the order follow the
	invoice would be worse: reopening a bill after its drawer was counted
	re-creates every hole `BR-044` closes.
	"""

	def _paid(self):
		_ensure_fiscal_year()

		order = self._order()
		orders.add_item(order, item=ITEM)
		order.reload()
		service.process_payment(order, payments=[{"method": CASH, "amount": order.total_amount}])
		order.reload()
		return order

	def test_the_desk_cannot_cancel_an_invoice_an_order_points_at(self):
		order = self._paid()

		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Sales Invoice", order.sales_invoice).cancel()

		self.assertEqual(
			frappe.db.get_value("Sales Invoice", order.sales_invoice, "docstatus"),
			1,
			"the invoice must still stand",
		)

	def test_an_invoice_with_no_order_behind_it_is_left_alone(self):
		"""The guard is about **our** sales; ERPNext's own invoices are its own."""
		order = self._paid()
		invoice = order.sales_invoice

		# Detach it, the way any invoice raised outside the till already is.
		frappe.db.set_value("Restaurant Order", order.name, "sales_invoice", None)
		frappe.get_doc("Sales Invoice", invoice).cancel()

		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice, "docstatus"), 2)

	def test_a_cancelled_invoice_stops_being_expected_in_the_till(self):
		"""D-062 — money the books gave back is not money in the till.

		The `docstatus` is set directly here rather than through `cancel()`,
		which the guard above now refuses. That is the point: this covers the
		**read**, not the cancel path — invoices cancelled before that guard
		existed, or by a future return flow, must not keep a cashier answering
		for cash the ledger already gave back.
		"""
		from restaurant_pos.utils import shift as shift_service

		order = self._paid()
		entry = shift_service.selling_till(self.profile).name

		expected = shift_service.summarise_till(entry)["till_expected"]
		self.assertGreater(expected, 0, "the sale should be expected in the drawer")

		frappe.db.set_value("Sales Invoice", order.sales_invoice, "docstatus", 2)

		after = shift_service.summarise_till(entry)["till_expected"]
		self.assertLess(after, expected, "a reversed sale must not stay in the count")


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

		_ensure_fiscal_year()

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

	def _a_method_off_the_terminal(self) -> str:
		name = "RPOS Not On This Till"
		if not frappe.db.exists("Mode of Payment", name):
			frappe.get_doc({"doctype": "Mode of Payment", "mode_of_payment": name, "type": "Bank"}).insert(
				ignore_permissions=True
			)
		return name

	def test_the_screen_offers_only_the_terminals_methods(self):
		"""D-224 — with no methods on the order type, the terminal's list is the list."""
		order = self._payable_order()
		off = self._a_method_off_the_terminal()
		if frappe.get_all("OT Payment Method", filters={"parent": order.order_type}, limit=1):
			self.skipTest("the order type carries its own methods")

		offered = [row["payment_method"] for row in api.get_payment_summary(order.name)["payment_methods"]]

		self.assertEqual(offered, service.terminal_methods(order.pos_profile))
		self.assertNotIn(off, offered)

	def test_a_method_not_on_the_terminal_is_refused(self):
		"""D-224 — the server refuses what the screen would not have offered."""
		order = self._payable_order()
		off = self._a_method_off_the_terminal()

		with self.assertRaises(frappe.ValidationError):
			service.process_payment(order, payments=[{"method": off, "amount": flt(order.total_amount)}])

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


class TestTheTillIsToldBeforeTheMoney(PaymentTestBase):
	"""D-125 — a fault the terminal already knows about is said on the screen.

	A POS Profile with no default customer used to raise from inside
	`_create_sales_invoice`, which is after the cashier has taken the cash and
	the drawer is open. Nothing the cashier types can get past it, so it belongs
	on the screen the moment it opens.
	"""

	def _without_a_default_customer(self):
		customer = frappe.db.get_value("POS Profile", self.profile, "customer")
		frappe.db.set_value("POS Profile", self.profile, "customer", None)
		frappe.clear_document_cache("POS Profile", self.profile)
		self.addCleanup(frappe.clear_document_cache, "POS Profile", self.profile)
		self.addCleanup(frappe.db.set_value, "POS Profile", self.profile, "customer", customer)

	def test_the_payment_screen_is_told_when_it_opens(self):
		order = self._payable_order()
		self._without_a_default_customer()

		self.assertTrue(api.get_payment_summary(order.name)["blocker"])

	def test_a_terminal_that_is_set_up_blocks_nothing(self):
		order = self._payable_order()
		self.assertIsNone(api.get_payment_summary(order.name)["blocker"])

	def test_nothing_is_charged_when_it_is_ignored(self):
		"""The screen is a courtesy; the refusal is still the server's."""
		order = self._payable_order()
		self._without_a_default_customer()

		with self.assertRaises(frappe.ValidationError):
			self._pay(order)

		order.reload()
		self.assertFalse(order.sales_invoice)
		self.assertNotEqual(order.status, "closed")


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
		table = frappe.db.get_value("Restaurant Table", {"section": self.section, "is_active": 1}, "name")
		free_table(table)

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

	def test_a_send_on_save_order_type_paid_at_once_still_reaches_the_kitchen(self):
		"""D-223 — a ``save`` type sends as the bill is put down; paying is putting it down."""
		frappe.db.set_value("Restaurant Order Type", self.order_type, "send_to_kitchen_on", "save")
		self.addCleanup(
			frappe.db.set_value, "Restaurant Order Type", self.order_type, "send_to_kitchen_on", "payment"
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


def _make_settler() -> str:
	"""A second cashier, distinct from the suite's own user and from the opener.

	`_make_cashier` hands back one shared login; a test about *handing a bill
	over* needs two different people in it, or it proves nothing about either.
	"""
	email = "rpos_settling_cashier@example.com"
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "RPOS Settling Cashier",
				"send_welcome_email": 0,
				"roles": [{"role": "POS Cashier"}],
			}
		).insert(ignore_permissions=True)

	return email


class TheBillIsFiledUnderWhoeverTookTheMoney(PaymentTestBase):
	"""`D-188` — and the drawer that holds the notes is the one that counts them.

	**The user's case, exactly.** Nora opened a bill; ruzmh settled it while
	signed in at the till. The list went on showing Nora, and the reason that
	mattered was not the label: `summarise_till` attributes a drawer's takings by
	`Restaurant Order.cashier`, so the money sat in ruzmh's drawer and was
	counted against Nora's — which had been counted and closed hours before.

	> الفاتورة تسجل باسم اللي أغلقها وليس اللي فتحها

	Nothing is lost by it. Frappe's own `owner` records who created the order,
	and the bill's story carries `opened` with their name (`D-106`).
	"""

	def _opened_by_somebody_else(self):
		"""A bill created by another cashier, then handed over unpaid.

		**A genuinely different person.** The first version of this named
		`Administrator` — which is the user the suite itself runs as, so
		`cashier == frappe.session.user` held before the change as well as
		after, and two mutations walked straight through a green test.
		"""
		order = self._payable_order()
		other = _make_cashier()
		self.assertNotEqual(other, frappe.session.user, "the fixture must hand over to somebody else")

		frappe.db.set_value("Restaurant Order", order.name, "cashier", other)
		order.reload()
		return order

	def test_settling_it_files_it_under_the_settler(self):
		"""**Driven as the settler**, not as whoever the suite happens to run as.

		Asserting `cashier == frappe.session.user` from the default session was
		too weak: `Administrator` is the suite's user *and* the owner of most
		fixtures, so an implementation filing the bill under the terminal's owner
		passed it. Paying as a named third person pins the claim to the actor.
		"""
		order = self._opened_by_somebody_else()
		settler = _make_settler()

		was = frappe.session.user
		frappe.set_user(settler)
		try:
			self._pay(order)
		finally:
			frappe.set_user(was)

		order.reload()
		self.assertEqual(order.cashier, settler)

	def test_who_opened_it_is_not_lost(self):
		"""`owner` is Frappe's own record of who created the document."""
		order = self._opened_by_somebody_else()
		opener = frappe.db.get_value("Restaurant Order", order.name, "owner")

		self._pay(order)

		self.assertEqual(frappe.db.get_value("Restaurant Order", order.name, "owner"), opener)

	def test_the_money_lands_in_the_drawer_that_holds_it(self):
		"""The half that is money rather than a label.

		The drawer counted what was **opened** inside it, so a bill opened before
		this drawer was taken — and settled into it — was in no drawer's figures
		at all: too early for the one holding the notes, and its opener's drawer
		was closed before the money arrived.
		"""
		from restaurant_pos.utils import shift as shift_service

		# A bill opened before this drawer exists, by somebody else.
		order = self._opened_by_somebody_else()
		frappe.db.set_value(
			"Restaurant Order", order.name, "opened_at", add_to_date(now_datetime(), hours=-3)
		)
		order.reload()

		for name in frappe.get_all(
			"POS Opening Entry", filters={"pos_profile": self.profile, "status": "Open"}, pluck="name"
		):
			frappe.db.set_value("POS Opening Entry", name, "status", "Closed")

		taken = shift_service.open_till(pos_profile=self.profile)
		self._pay(order)

		report = shift_service.summarise_till(taken["entry"])

		self.assertEqual(report["orders"]["closed"], 1, "the drawer counts what it settled")
		self.assertGreater(report["till_expected"], 0.0)

	def test_the_bill_names_the_drawer_it_was_settled_into(self):
		"""D-227 — written at payment, so a report reads it instead of deriving it."""
		from restaurant_pos.utils import shift as shift_service

		order = self._payable_order()
		drawer = shift_service.selling_till(self.profile)
		self._pay(order)

		self.assertEqual(
			frappe.db.get_value("Restaurant Order", order.name, "pos_opening_entry"), drawer.name
		)

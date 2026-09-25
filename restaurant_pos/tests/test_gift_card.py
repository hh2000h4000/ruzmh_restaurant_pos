# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Money the guest handed over before they ate (`D-256`).

**The claims worth holding are the ones a discount would get wrong.** A card
pays a bill rather than reducing it, so the invoice keeps its full price and its
full VAT; selling a card is not a sale, so no invoice is raised for it and the
liability rises instead; and the cash it brought in is in the drawer, so the
count has to expect it.

Refs: FR-11.5, D-029, D-256
"""

import frappe
from frappe.utils import flt

from restaurant_pos.setup.gift_card_accounts import MODE_OF_PAYMENT
from restaurant_pos.tests.test_order import ITEM
from restaurant_pos.tests.test_payment import CASH, PaymentTestBase
from restaurant_pos.utils import gift_card as cards
from restaurant_pos.utils import order as orders
from restaurant_pos.utils import payment, returns
from restaurant_pos.utils import shift as service

PREFIX = "RPOSGC"


def _offer_the_card_at_the_till(profile: str) -> None:
	"""Put the gift-card method on the terminal, as a manager would.

	**Not shipped switched on**, and deliberately (`D-224`): the user asked that
	a till show only the methods they chose, so a new method appearing on every
	terminal by itself would undo that. The setup creates the method and the
	account; offering it is a decision.
	"""
	terminal = frappe.get_doc("POS Profile", profile)
	if any(row.mode_of_payment == MODE_OF_PAYMENT for row in terminal.payments):
		return

	terminal.append("payments", {"mode_of_payment": MODE_OF_PAYMENT, "default": 0})
	terminal.save(ignore_permissions=True)


class GiftCardTestBase(PaymentTestBase):
	def setUp(self):
		super().setUp()
		self._clear()
		_offer_the_card_at_the_till(self.profile)

	def tearDown(self):
		self._clear()
		super().tearDown()

	def _clear(self) -> None:
		for card in frappe.get_all("POS Gift Card", filters={"name": ("like", f"{PREFIX}%")}, pluck="name"):
			for entry in frappe.get_all("POS Gift Card Entry", filters={"gift_card": card}, pluck="name"):
				frappe.db.delete("POS Gift Card Entry", entry)
			frappe.db.delete("POS Gift Card", card)

	def _sell(self, number: str = f"{PREFIX}1", amount: float = 200, **fields) -> dict:
		return cards.issue(
			self.profile,
			card_number=number,
			amount=amount,
			mode_of_payment=fields.pop("mode_of_payment", CASH),
			**fields,
		)

	def _bill(self, qty: float = 1):
		order = self._order()
		orders.add_item(order, item=ITEM, qty=qty)
		order.reload()
		return order


class SellingACard(GiftCardTestBase):
	def test_the_card_carries_what_was_paid_for_it(self):
		sold = self._sell(amount=200)

		self.assertEqual(sold["balance"], 200)
		self.assertEqual(cards.balance_of(f"{PREFIX}1"), 200)

	def test_selling_one_raises_no_invoice(self):
		"""**Article 19.** A face-value voucher sold at face value is no supply,
		so there is no sale to invoice and no VAT to charge — the tax falls later,
		on the food."""
		before = frappe.db.count("Sales Invoice")

		self._sell()

		self.assertEqual(frappe.db.count("Sales Invoice"), before)

	def test_the_number_is_read_however_it_was_typed(self):
		self._sell(number=f"{PREFIX}1")

		self.assertEqual(cards.balance_of(f"  {PREFIX.lower()}1  "), 200)

	def test_one_number_cannot_be_sold_twice(self):
		self._sell()

		with self.assertRaises(frappe.ValidationError):
			self._sell()

	def test_a_repeated_request_sells_one_card_not_two(self):
		"""The offline queue re-sends; the guest paid once (`09` §8)."""
		first = self._sell(queue_id="RPOS-GC-QUEUE-1")
		second = cards.issue(
			self.profile,
			card_number=f"{PREFIX}1",
			amount=200,
			mode_of_payment=CASH,
			queue_id="RPOS-GC-QUEUE-1",
		)

		self.assertEqual(second["gift_card"], first["gift_card"])
		self.assertTrue(second.get("repeated"))
		self.assertEqual(frappe.db.count("POS Gift Card", {"card_number": f"{PREFIX}1"}), 1)


class SpendingACard(GiftCardTestBase):
	def test_it_pays_the_bill_in_full_and_the_balance_drops(self):
		self._sell(amount=200)
		order = self._bill()
		due = flt(order.total_amount)

		payment.process_payment(
			order,
			payments=[{"method": MODE_OF_PAYMENT, "amount": due, "gift_card": f"{PREFIX}1"}],
		)

		order.reload()
		self.assertEqual(order.status, "closed")
		self.assertAlmostEqual(cards.balance_of(f"{PREFIX}1"), 200 - due, places=2)

	def test_the_bill_is_the_same_bill_as_if_it_had_been_paid_in_cash(self):
		"""**The difference from a coupon, in one comparison.**

		A discount shrinks the taxable amount; a card does not. So the invoice a
		card settles must match, figure for figure, the one the same order would
		have produced paid in notes — total and tax alike.

		Compared against a cash bill rather than asserted against a number: what
		VAT this site charges is a property of its tax template, and a test that
		hard-codes a rate is testing the fixture.
		"""
		self._sell(amount=200)
		by_card = self._bill()
		due = flt(by_card.total_amount)
		payment.process_payment(
			by_card,
			payments=[{"method": MODE_OF_PAYMENT, "amount": due, "gift_card": f"{PREFIX}1"}],
		)

		in_cash = self._bill()
		payment.process_payment(in_cash, payments=[{"method": CASH, "amount": flt(in_cash.total_amount)}])

		by_card.reload()
		in_cash.reload()
		card_invoice = frappe.get_doc("Sales Invoice", by_card.sales_invoice)
		cash_invoice = frappe.get_doc("Sales Invoice", in_cash.sales_invoice)

		self.assertAlmostEqual(flt(card_invoice.grand_total), flt(cash_invoice.grand_total), places=2)
		self.assertAlmostEqual(
			flt(card_invoice.total_taxes_and_charges),
			flt(cash_invoice.total_taxes_and_charges),
			places=2,
			msg="a card pays the bill, it does not discount it",
		)
		self.assertAlmostEqual(flt(card_invoice.discount_amount), 0, places=2)

	def test_a_card_without_enough_left_is_refused_before_anything_posts(self):
		self._sell(amount=1)
		order = self._bill()
		invoices = frappe.db.count("Sales Invoice")

		with self.assertRaises(frappe.ValidationError):
			payment.process_payment(
				order,
				payments=[
					{
						"method": MODE_OF_PAYMENT,
						"amount": flt(order.total_amount),
						"gift_card": f"{PREFIX}1",
					}
				],
			)

		order.reload()
		self.assertNotEqual(order.status, "closed")
		self.assertEqual(frappe.db.count("Sales Invoice"), invoices, "nothing was posted")

	def test_a_payment_row_that_names_no_card_is_refused(self):
		order = self._bill()

		with self.assertRaises(frappe.ValidationError):
			payment.process_payment(
				order, payments=[{"method": MODE_OF_PAYMENT, "amount": flt(order.total_amount)}]
			)

	def test_a_switched_off_card_is_refused_by_name(self):
		self._sell()
		# A card reported lost: the number still exists and must stop working.
		frappe.db.set_value("POS Gift Card", f"{PREFIX}1", "is_active", 0)

		with self.assertRaises(frappe.ValidationError):
			cards.find(f"{PREFIX}1")


class WhatTheDrawerExpects(GiftCardTestBase):
	def test_selling_a_card_for_cash_is_money_the_count_asks_for(self):
		"""`D-256` — a card sale reaches no invoice, so without this the cashier
		counts more notes than the screen ever asked for."""
		entry = service.open_till(pos_profile=self.profile)["entry"]
		before = service.summarise_till(entry)["till_expected"]

		self._sell(amount=150)

		after = service.summarise_till(entry)["till_expected"]
		self.assertAlmostEqual(after - before, 150, places=2)

	def test_spending_a_card_puts_nothing_in_the_drawer(self):
		"""The money arrived when the card was sold; expecting it twice is a
		drawer told to hold cash nobody put there (`D-029`)."""
		self._sell(amount=200)
		entry = service.open_till(pos_profile=self.profile)["entry"]
		before = service.summarise_till(entry)["till_expected"]
		order = self._bill()

		payment.process_payment(
			order,
			payments=[
				{"method": MODE_OF_PAYMENT, "amount": flt(order.total_amount), "gift_card": f"{PREFIX}1"}
			],
		)

		after = service.summarise_till(entry)["till_expected"]
		self.assertAlmostEqual(after, before, places=2)


class TheLedgerActuallyMoves(GiftCardTestBase):
	"""**The claim the whole design rests on** (`D-257`).

	Selling a card credits the liability; spending one must debit it. If it does
	not, the account's balance stops being the outstanding gift-card liability,
	the "it reconciles against itself" promise is empty, and every card-paid bill
	quietly leaves a receivable against the walk-in customer instead.

	Asserted against the general ledger rather than against our own entries: our
	rows could be perfect while the books say something else entirely.
	"""

	def _liability(self) -> str:
		return frappe.db.get_value("Mode of Payment Account", {"parent": MODE_OF_PAYMENT}, "default_account")

	def test_spending_a_card_debits_the_liability_account(self):
		self._sell(amount=200)
		order = self._bill()
		due = flt(order.total_amount)

		payment.process_payment(
			order,
			payments=[{"method": MODE_OF_PAYMENT, "amount": due, "gift_card": f"{PREFIX}1"}],
		)

		order.reload()
		posted = frappe.get_all(
			"GL Entry",
			filters={"voucher_no": order.sales_invoice, "account": self._liability()},
			fields=["debit", "credit"],
		)

		self.assertTrue(posted, "the liability account is not in this invoice's ledger at all")
		self.assertAlmostEqual(sum(flt(row.debit) for row in posted), due, places=2)

	def test_a_card_paid_bill_leaves_nothing_outstanding(self):
		"""It was paid. A receivable here is a debt against a guest who owes nothing."""
		self._sell(amount=200)
		order = self._bill()

		payment.process_payment(
			order,
			payments=[
				{"method": MODE_OF_PAYMENT, "amount": flt(order.total_amount), "gift_card": f"{PREFIX}1"}
			],
		)

		order.reload()
		self.assertAlmostEqual(
			flt(frappe.db.get_value("Sales Invoice", order.sales_invoice, "outstanding_amount")),
			0,
			places=2,
		)

	def test_a_card_can_pay_part_of_a_bill_and_cash_the_rest(self):
		"""The guide says this works, so it has to (`D-256`)."""
		self._sell(amount=5)
		order = self._bill()
		due = flt(order.total_amount)

		payment.process_payment(
			order,
			payments=[
				{"method": MODE_OF_PAYMENT, "amount": 5, "gift_card": f"{PREFIX}1"},
				{"method": CASH, "amount": due - 5},
			],
		)

		order.reload()
		self.assertEqual(order.status, "closed")
		self.assertAlmostEqual(cards.balance_of(f"{PREFIX}1"), 0, places=2)


class ReturningABillACardPaid(GiftCardTestBase):
	"""Back to the card it came off (`D-258`).

	Square refunds to the original tender and Toast refuses anything else on a
	card payment. The reason is a fraud path, not tidiness: notes handed back for
	a card-settled bill turn prepaid credit into cash — how a card bought with a
	stolen payment card gets emptied.
	"""

	def _row(self, order) -> str:
		return frappe.db.get_value("Sales Invoice Item", {"parent": order.sales_invoice}, "name")

	def _paid_by_card(self, loaded: float = 200):
		self._sell(amount=loaded)
		order = self._bill()
		payment.process_payment(
			order,
			payments=[
				{"method": MODE_OF_PAYMENT, "amount": flt(order.total_amount), "gift_card": f"{PREFIX}1"}
			],
		)
		order.reload()
		return order

	def test_the_money_goes_back_onto_the_card(self):
		order = self._paid_by_card()
		spent = flt(order.total_amount)
		self.assertAlmostEqual(cards.balance_of(f"{PREFIX}1"), 200 - spent, places=2)

		returns.create_return(
			order,
			items=[{"row": self._row(order), "qty": 1}],
			reason_code="goods_returned",
			refund_method=MODE_OF_PAYMENT,
		)

		# The whole bill was one line of one, so the card is whole again.
		self.assertAlmostEqual(cards.balance_of(f"{PREFIX}1"), 200, places=2)

	def test_cash_cannot_be_handed_back_for_money_that_came_off_a_card(self):
		"""The whole point of the rule: no cashing a card out through the till."""
		order = self._paid_by_card()

		with self.assertRaises(frappe.ValidationError) as refusal:
			returns.create_return(
				order,
				items=[{"row": self._row(order), "qty": 1}],
				reason_code="goods_returned",
				refund_method=CASH,
			)

		self.assertIn(CASH, str(refusal.exception))
		self.assertAlmostEqual(
			cards.balance_of(f"{PREFIX}1"), 200 - flt(order.total_amount), places=2, msg="nothing moved"
		)

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

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from restaurant_pos.setup import gift_card_accounts
from restaurant_pos.setup.gift_card_accounts import MODE_OF_PAYMENT
from restaurant_pos.tests.test_order import ITEM
from restaurant_pos.tests.test_payment import CASH, PaymentTestBase
from restaurant_pos.utils import gift_card as cards
from restaurant_pos.utils import order as orders
from restaurant_pos.utils import payment, returns
from restaurant_pos.utils import shift as service

PREFIX = "RPOSGC"


def _a_customer() -> str:
	"""Somebody for the cards to be issued to — a company, in the real case."""
	name = "RPOS Gift Card Co"
	if not frappe.db.exists("Customer", name):
		# The group and territory are named rather than left to the site's
		# defaults: this site's default customer group is a group node, which
		# ERPNext refuses, and a fixture leaning on a site setting breaks on
		# somebody else's site.
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": name,
				"customer_type": "Company",
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
				"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
			}
		).insert(ignore_permissions=True)

	return name


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


class WhatTheAccountantReads(GiftCardTestBase):
	"""The liability, card by card, on a chosen day (`D-259`).

	The point of the report is that its total can be held against the liability
	account's balance. So what is asserted is that it counts the same money the
	ledger does — and that it answers for a **date**, because a month-end entry is
	made in the second week of the month after it.
	"""

	def _rows(self, **filters) -> list[dict]:
		from restaurant_pos.restaurant_pos.report.gift_card_balances import gift_card_balances as report

		_columns, rows = report.execute(filters)
		return [row for row in rows if row["card_number"].startswith(PREFIX)]

	def test_an_unspent_card_is_owed_in_full(self):
		self._sell(amount=200)

		(row,) = self._rows(on=frappe.utils.today())

		self.assertAlmostEqual(row["balance"], 200, places=2)
		self.assertAlmostEqual(row["initial_value"], 200, places=2)

	def test_spending_takes_it_off_what_is_owed(self):
		self._sell(amount=200)
		order = self._bill()
		spent = flt(order.total_amount)
		payment.process_payment(
			order,
			payments=[{"method": MODE_OF_PAYMENT, "amount": spent, "gift_card": f"{PREFIX}1"}],
		)

		(row,) = self._rows(on=frappe.utils.today())

		self.assertAlmostEqual(row["balance"], 200 - spent, places=2)

	def test_a_card_sold_after_the_date_is_not_owed_on_it(self):
		"""Yesterday's books do not carry today's cards."""
		self._sell(amount=200)

		self.assertFalse(self._rows(on=frappe.utils.add_days(frappe.utils.today(), -1)))

	def test_a_switched_off_card_is_listed_and_marked_rather_than_dropped(self):
		"""Whether it is still owed is the accountant's call, not a report's."""
		self._sell(amount=200)
		frappe.db.set_value("POS Gift Card", f"{PREFIX}1", "is_active", 0)

		(row,) = self._rows(on=frappe.utils.today())

		self.assertAlmostEqual(row["balance"], 200, places=2)
		self.assertTrue(row["note"])


class IssuingFromTheOffice(GiftCardTestBase):
	"""Cards a company ordered, or one written off as an apology (`D-260`).

	The user asked the question that found this: *should a company not order
	cards and have them settled from the back office rather than the till?* Both
	happen, and only the till half was built — and a card typed into the desk by
	hand showed a balance its ledger did not have.
	"""

	def _issued(self, **fields) -> dict:
		from restaurant_pos.api import gift_card as api

		return api.issue_from_the_office(
			count=fields.pop("count", 2),
			amount=fields.pop("amount", 100),
			customer=fields.pop("customer", _a_customer()),
			**fields,
		)

	def test_the_cards_carry_what_was_issued_on_them(self):
		made = self._issued(count=3, amount=100, pattern="sequential", start="1", prefix=PREFIX)

		self.assertEqual(len(made["cards"]), 3)
		for card in made["cards"]:
			self.assertAlmostEqual(cards.balance_of(card), 100, places=2)

	def test_they_are_spendable_at_the_till(self):
		"""The point of the whole thing: the company's staff walk in and eat."""
		made = self._issued(count=1, amount=200, pattern="sequential", start="1", prefix=PREFIX)
		order = self._bill()

		payment.process_payment(
			order,
			payments=[
				{
					"method": MODE_OF_PAYMENT,
					"amount": flt(order.total_amount),
					"gift_card": made["cards"][0],
				}
			],
		)

		order.reload()
		self.assertEqual(order.status, "closed")

	def test_the_money_is_owed_by_the_customer_not_taken_from_a_drawer(self):
		"""Fifty cards to a company are a receivable, not cash in anybody's till."""
		entry = service.open_till(pos_profile=self.profile)["entry"]
		before = service.summarise_till(entry)["till_expected"]

		self._issued(count=2, amount=100, pattern="sequential", start="1", prefix=PREFIX)

		self.assertAlmostEqual(service.summarise_till(entry)["till_expected"], before, places=2)

	def test_a_card_typed_in_by_hand_never_claims_a_balance_it_has_not_got(self):
		"""Two screens disagreeing about money is the worst shape a defect takes."""
		card = frappe.get_doc(
			{
				"doctype": "POS Gift Card",
				"card_number": f"{PREFIX}BYHAND",
				"balance": 200,
				"initial_value": 200,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)

		self.assertAlmostEqual(flt(card.balance), 0, places=2)
		self.assertAlmostEqual(cards.balance_of(card.name), 0, places=2)


class AnotherAppsRequiredField(FrappeTestCase):
	"""`D-262` — `ksa_compliance` requires a ZATCA code on every payment mode.

	The mode was refused, the refusal escaped `after_migrate`, and every step
	after it stopped on the user's site — migrate after migrate, unseen. The code
	is a tax answer, so it is not invented here: it is said, and setup goes on.
	"""

	def test_a_refused_mode_is_logged_and_does_not_stop_setup(self):
		refused = frappe.MandatoryError("[Mode of Payment, x]: custom_zatca_payment_means_code")
		with patch.object(gift_card_accounts, "_ensure_mode", side_effect=refused):
			result = gift_card_accounts.setup()

		self.assertIsNone(result["mode_of_payment"])
		logged = frappe.get_all(
			"Error Log", filters={"method": ("like", f"%{MODE_OF_PAYMENT}%")}, pluck="error", limit=1
		)
		self.assertTrue(logged)
		self.assertIn("custom_zatca_payment_means_code", logged[0])


class NoCardByHand(FrappeTestCase):
	"""`D-263` — the list's «إضافة» made a card with no entry, so no money on it.

	The balance is the sum of the entries, so a card typed in by hand showed
	zero and was refused at the till — beside «إصدار بطاقات», which asks the
	same question and answers it properly. One way in, and it posts the entry.
	"""

	def test_the_office_cannot_create_a_card_by_hand(self):
		self.assertEqual(frappe.get_meta("POS Gift Card").in_create, 1)


class TheTickNotTheName(GiftCardTestBase):
	"""`D-264` — a gift card method is the one ticked, whatever it is called.

	It was the name. The first site to make its own called it «بطاقة هدية»
	against the code's «بطاقة هدايا», and the till would have taken it like cash
	and asked for no card. A name is a label for people, in their language.
	"""

	OTHER = "RPOS Test Gifts"

	def _ticked(self, name: str) -> None:
		was = frappe.db.get_value("Mode of Payment", {"rpos_is_gift_card": 1}, "name")
		company = frappe.db.get_value("POS Profile", self.profile, "company")
		liability = cards._liability(company)
		if not frappe.db.exists("Mode of Payment", name):
			frappe.get_doc({"doctype": "Mode of Payment", "mode_of_payment": name, "type": "General"}).insert(
				ignore_permissions=True
			)
		mode = frappe.get_doc("Mode of Payment", name)
		if not any(row.company == company for row in mode.accounts):
			mode.append("accounts", {"company": company, "default_account": liability})
			mode.save(ignore_permissions=True)

		frappe.db.set_value("Mode of Payment", was, "rpos_is_gift_card", 0)
		frappe.db.set_value("Mode of Payment", name, "rpos_is_gift_card", 1)
		self.addCleanup(frappe.db.set_value, "Mode of Payment", name, "rpos_is_gift_card", 0)
		self.addCleanup(frappe.db.set_value, "Mode of Payment", was, "rpos_is_gift_card", 1)

		terminal = frappe.get_doc("POS Profile", self.profile)
		if not any(row.mode_of_payment == name for row in terminal.payments):
			terminal.append("payments", {"mode_of_payment": name, "default": 0})
			terminal.save(ignore_permissions=True)

	def test_a_method_with_another_name_spends_the_card(self):
		self._sell(amount=200)
		self._ticked(self.OTHER)
		order = self._bill()
		due = flt(order.total_amount)

		payment.process_payment(
			order, payments=[{"method": self.OTHER, "amount": due, "gift_card": f"{PREFIX}1"}]
		)

		self.assertEqual(flt(frappe.db.get_value("POS Gift Card", f"{PREFIX}1", "balance")), flt(200 - due))

	def test_the_old_name_unticked_is_an_ordinary_method(self):
		self._ticked(self.OTHER)

		self.assertFalse(cards.is_gift_card_method(MODE_OF_PAYMENT))
		self.assertTrue(cards.is_gift_card_method(self.OTHER))

	def test_a_second_ticked_method_is_refused(self):
		if not frappe.db.exists("Mode of Payment", self.OTHER):
			frappe.get_doc(
				{"doctype": "Mode of Payment", "mode_of_payment": self.OTHER, "type": "General"}
			).insert(ignore_permissions=True)
		mode = frappe.get_doc("Mode of Payment", self.OTHER)
		mode.rpos_is_gift_card = 1

		with self.assertRaises(frappe.ValidationError):
			mode.save(ignore_permissions=True)

	def test_a_method_both_gift_card_and_credit_is_refused(self):
		mode = frappe.get_doc("Mode of Payment", cards.gift_card_method())
		mode.rpos_is_credit = 1

		with self.assertRaises(frappe.ValidationError):
			mode.save(ignore_permissions=True)

	def test_setup_ticks_the_method_it_used_to_find_by_name(self):
		frappe.db.set_value("Mode of Payment", MODE_OF_PAYMENT, "rpos_is_gift_card", 0)
		self.addCleanup(frappe.db.set_value, "Mode of Payment", MODE_OF_PAYMENT, "rpos_is_gift_card", 1)

		gift_card_accounts.setup()

		self.assertEqual(cards.gift_card_method(), MODE_OF_PAYMENT)

	def test_a_cash_account_on_the_gift_card_method_is_refused(self):
		"""`D-265` — the manager who could not pick the liability made a cash one."""
		mode = frappe.get_doc("Mode of Payment", cards.gift_card_method())
		company = frappe.db.get_value("POS Profile", self.profile, "company")
		cash = frappe.db.get_value(
			"Account", {"account_type": "Cash", "company": company, "is_group": 0}, "name"
		)
		next(row for row in mode.accounts if row.company == company).default_account = cash

		with self.assertRaises(frappe.ValidationError):
			mode.save(ignore_permissions=True)


class NoEntryNoCard(GiftCardTestBase):
	"""`D-266` — a card the books do not owe is not issued at all.

	It used to be issued with «not posted» on it. The user's first two cards went
	out so — 400 promised to guests, and nothing on the liability account.
	"""

	def _unmarked(self) -> None:
		method = cards.gift_card_method()
		frappe.db.set_value("Mode of Payment", method, "rpos_is_gift_card", 0)
		self.addCleanup(frappe.db.set_value, "Mode of Payment", method, "rpos_is_gift_card", 1)

	def test_the_till_will_not_sell_a_card_the_books_cannot_owe(self):
		self._unmarked()

		with self.assertRaises(frappe.ValidationError):
			self._sell(number=f"{PREFIX}9")
		self.assertFalse(frappe.db.exists("POS Gift Card", {"card_number": f"{PREFIX}9"}))

	def test_the_office_will_not_issue_one_either(self):
		from restaurant_pos.api import gift_card as api

		self._unmarked()

		before = frappe.db.count("POS Gift Card")
		with self.assertRaises(frappe.ValidationError):
			api.issue_from_the_office(count=1, amount=100, customer=_a_customer(), prefix=PREFIX)
		self.assertEqual(frappe.db.count("POS Gift Card"), before)


class CancellingACard(GiftCardTestBase):
	"""`D-267` — undoing a card issued by mistake, the way Toast and Square do.

	The user asked why a card with nothing on it could not be deleted. The answer
	is two actions: a card the books know is **cancelled** — its entry reversed,
	the card kept — and only a record the books never saw is **deleted**.
	"""

	def _net_on(self, account: str, vouchers: list[str]) -> float:
		rows = frappe.get_all(
			"GL Entry",
			filters={"account": account, "voucher_no": ("in", vouchers), "is_cancelled": 0},
			fields=["debit", "credit"],
		)
		return sum(flt(row.credit) - flt(row.debit) for row in rows)

	def _entries(self, card: str) -> list:
		return frappe.get_all(
			"POS Gift Card Entry", filters={"gift_card": card}, fields=["entry_type", "journal_entry"]
		)

	def test_an_office_card_is_cancelled_and_the_customer_owes_nothing_for_it(self):
		from restaurant_pos.api import gift_card as api

		made = api.issue_from_the_office(count=1, amount=100, customer=_a_customer(), prefix=PREFIX)
		card = made["cards"][0]

		result = cards.void(card, "wrong amount")

		vouchers = [made["journal_entry"], *result["journal_entries"]]
		company = frappe.db.get_value("POS Profile", self.profile, "company")
		self.assertEqual(self._net_on(cards._liability(company), vouchers), 0)
		receivable = frappe.db.get_value("Company", company, "default_receivable_account")
		self.assertEqual(self._net_on(receivable, vouchers), 0)
		self.assertEqual(flt(frappe.db.get_value("POS Gift Card", card, "balance")), 0)
		self.assertEqual(frappe.db.get_value("POS Gift Card", card, "is_active"), 0)

	def test_a_card_sold_at_the_till_hands_its_money_back_out_of_the_drawer(self):
		entry = service.open_till(pos_profile=self.profile)["entry"]
		before = service.summarise_till(entry)["till_expected"]
		sold = self._sell(amount=150)

		cards.void(sold["gift_card"], "sold by mistake")

		after = service.summarise_till(entry)["till_expected"]
		self.assertAlmostEqual(after, before, places=2)

	def test_a_card_spent_from_is_not_cancelled(self):
		sold = self._sell(amount=200)
		order = self._bill()
		payment.process_payment(
			order,
			payments=[
				{"method": MODE_OF_PAYMENT, "amount": flt(order.total_amount), "gift_card": f"{PREFIX}1"}
			],
		)

		with self.assertRaises(frappe.ValidationError):
			cards.void(sold["gift_card"], "changed their mind")

	def test_a_card_is_cancelled_once(self):
		sold = self._sell(amount=100)
		cards.void(sold["gift_card"], "mistake")

		with self.assertRaises(frappe.ValidationError):
			cards.void(sold["gift_card"], "again")

	def test_a_card_whose_drawer_has_closed_is_not_cancelled(self):
		sold = self._sell(amount=100)
		till = frappe.db.get_value(
			"POS Gift Card Entry", {"gift_card": sold["gift_card"]}, "pos_opening_entry"
		)
		frappe.db.set_value("POS Opening Entry", till, "status", "Closed")
		self.addCleanup(frappe.db.set_value, "POS Opening Entry", till, "status", "Open")

		with self.assertRaises(frappe.ValidationError):
			cards.void(sold["gift_card"], "too late")

	def test_a_card_the_books_know_is_not_deleted(self):
		sold = self._sell(amount=100)

		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("POS Gift Card", sold["gift_card"], ignore_permissions=True)

	def test_a_record_the_books_never_saw_is_deleted_with_its_rows(self):
		card = frappe.get_doc(
			{"doctype": "POS Gift Card", "card_number": f"{PREFIX}X", "is_active": 1}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{"doctype": "POS Gift Card Entry", "gift_card": card.name, "entry_type": "issue", "amount": 50}
		).insert(ignore_permissions=True)

		frappe.delete_doc("POS Gift Card", card.name, ignore_permissions=True)

		self.assertFalse(frappe.db.exists("POS Gift Card", card.name))
		self.assertFalse(self._entries(card.name))

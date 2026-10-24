"""A whole sale on every kind of terminal the branch change leaves (`D-394`).

Stage 4 of separating a terminal from its hall. The terminal the rest of the
suite sells from is the migrated kind — its branch column filled, a hall on it.
These run the same sale on the two others:

* **an old terminal** — its column empty, as on a site whose migrate has not
  filled it yet. Everything falls back to its hall's branch (`D-393`).
* **a terminal with a branch and no hall** — what a counter or a supermarket
  till is once the hall is optional.

Each one opens an order, sends it to the kitchen, takes cash, and refunds a
part: the invoice, its number, the tax, the warehouse it sells from and the
branch on every document must come out as they do on the suite's own terminal.

And the history: a terminal that sold before its column was filled keeps its
sequence after it, and a terminal that has sold cannot be moved to another
branch.

Refs: D-309, D-337, D-391, D-392, D-393, D-394
"""

import frappe
from frappe.utils import cint, flt

from restaurant_pos.tests.test_order import ITEM
from restaurant_pos.tests.test_returns import REASON, ReturnTestBase
from restaurant_pos.utils import kitchen, terminal_branch
from restaurant_pos.utils import order as orders
from restaurant_pos.utils import returns as returns_service
from restaurant_pos.utils.invoice_number import BRANCH_NUMBER, DEVICE_NUMBER
from restaurant_pos.utils.sale_doc import SALE


class TerminalKindsBase(ReturnTestBase):
	"""The suite's terminal, turned into each kind for the length of one test."""

	def setUp(self):
		super().setUp()
		self.branch = terminal_branch.branch_of(self.profile)
		self.hall = frappe.db.get_value("POS Profile", self.profile, "restaurant_section")

	def tearDown(self):
		frappe.db.set_value(
			"POS Profile",
			self.profile,
			{"restaurant_section": self.hall, terminal_branch.FIELD: self.branch},
			update_modified=False,
		)
		super().tearDown()

	def _as_old_terminal(self):
		"""Column empty: the site has the code but has not migrated."""
		frappe.db.set_value("POS Profile", self.profile, terminal_branch.FIELD, None, update_modified=False)

	def _as_hall_less_terminal(self):
		"""A branch and no hall."""
		frappe.db.set_value(
			"POS Profile",
			self.profile,
			{"restaurant_section": None, terminal_branch.FIELD: self.branch},
			update_modified=False,
		)

	def _a_whole_sale(self):
		"""Open, cook, pay, refund one — and check what each step left behind."""
		order = self._order()
		# Routed to a station of the branch: an item no station takes gets no
		# ticket (`D-396`), and the kitchen step would test nothing.
		station = frappe.get_all(
			"Production Center", filters={"branch": self.branch, "is_active": 1}, pluck="name", limit=1
		)
		if not station:
			self.skipTest("the test branch has no station")
		own = frappe.db.get_value("Item", ITEM, "default_production_center")
		frappe.db.set_value("Item", ITEM, "default_production_center", station[0])
		try:
			orders.add_item(order, item=ITEM, qty=2)
			order.reload()
			sent = kitchen.send_to_kitchen(order)
		finally:
			frappe.db.set_value("Item", ITEM, "default_production_center", own)
		order.reload()
		from restaurant_pos.tests.test_payment import CASH, _ensure_fiscal_year
		from restaurant_pos.utils import payment

		_ensure_fiscal_year()
		payment.process_payment(order, payments=[{"method": CASH, "amount": order.total_amount}])
		order.reload()

		self.assertEqual(order.branch, self.branch)
		self.assertEqual(order.status, "closed")
		self.assertTrue(sent["kots_created"])

		invoice = frappe.get_doc(SALE, order.sales_invoice)
		prefix = "{}-{}-".format(
			frappe.db.get_value("Branch", self.branch, BRANCH_NUMBER),
			frappe.db.get_value("POS Profile", self.profile, DEVICE_NUMBER),
		)
		self.assertTrue(invoice.name.startswith(prefix), invoice.name)
		# The tax the till quoted is the tax invoiced (the suite's terminal may
		# carry no template, so the figure itself is not asserted).
		self.assertAlmostEqual(flt(invoice.total_taxes_and_charges), flt(order.tax_amount), places=2)
		self.assertEqual(
			invoice.items[0].warehouse, frappe.db.get_value("POS Profile", self.profile, "warehouse")
		)
		self.assertEqual(invoice.pos_profile, self.profile)

		row = returns_service.returnable(order)["items"][0]["row"]
		result = returns_service.create_return(order, items=[{"row": row, "qty": 1}], reason_code=REASON)
		self.assertGreater(result["refund_amount"], 0)
		return order


class TestAnOldTerminal(TerminalKindsBase):
	def test_it_sells_cooks_pays_and_refunds_as_before(self):
		self._as_old_terminal()
		self.assertEqual(terminal_branch.branch_of(self.profile), self.branch)
		self._a_whole_sale()


class TestATerminalWithNoHall(TerminalKindsBase):
	def test_it_sells_cooks_pays_and_refunds(self):
		self._as_hall_less_terminal()
		self.assertEqual(terminal_branch.branch_of(self.profile), self.branch)
		order = self._a_whole_sale()
		# No table and no hall: the order is in no hall, and says so.
		self.assertFalse(order.section)

	def test_it_is_counted_with_its_branch(self):
		self._as_hall_less_terminal()
		self.assertIn(self.profile, orders.profiles_in(self.branch))


class TestTheHistory(TerminalKindsBase):
	def test_filling_the_column_keeps_the_sequence(self):
		"""A terminal that sold before the patch counts on from where it was."""
		self._as_old_terminal()
		before = self._a_whole_sale()

		terminal_branch.fill_from_halls()
		self.assertEqual(frappe.db.get_value("POS Profile", self.profile, terminal_branch.FIELD), self.branch)

		after = self._a_whole_sale()
		self.assertEqual(after.branch, before.branch)
		# The refund in between took the next number, so the sale after the
		# patch is two on: one sequence, unbroken by the column being filled.
		self.assertEqual(
			cint(after.sales_invoice.rsplit("-", 1)[1]),
			cint(before.sales_invoice.rsplit("-", 1)[1]) + 2,
			(before.sales_invoice, after.sales_invoice),
		)

	def test_a_terminal_that_has_sold_cannot_move_branch(self):
		"""Its invoices are numbered in its branch; moving it would split the sequence."""
		self._a_whole_sale()
		other = frappe.get_all("Branch", filters={"name": ("!=", self.branch)}, pluck="name", limit=1)
		if not other:
			self.skipTest("this site has one branch")

		doc = frappe.get_doc("POS Profile", self.profile)
		doc.restaurant_section = None
		doc.set(terminal_branch.FIELD, other[0])
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

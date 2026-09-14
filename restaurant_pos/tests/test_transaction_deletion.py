# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""ERPNext's Delete Transactions clears the till too (`D-210`).

Every test submits the real `Transaction Deletion Record`, the way the Company
button does first, so what is proven is the hook — not a function called by
hand. Submitting only *queues* ERPNext's own half; `start_deletion_tasks` runs
it, and nothing here calls that, so the test site's invoices are left alone.

Refs: D-061, D-210
"""

import frappe

from restaurant_pos.tests.test_order import BRANCH, OrderTestBase, _ensure_shift
from restaurant_pos.tests.test_permissions import _make_user
from restaurant_pos.utils import idempotency
from restaurant_pos.utils.audit import log_audit

#: Setup a restaurant made before its first order. Never touched.
SETUP = (
	"Restaurant Order Type",
	"Restaurant Section",
	"Restaurant Table",
	"POS Permission Set",
	"POS Printer",
)

RESTAURANT_ADMIN = "rpos_deletion_restaurant_admin@example.com"


class TestDeleteTransactionsClearsTheTill(OrderTestBase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = frappe.db.get_value("Branch", BRANCH, "company")
		cls.section = frappe.db.get_value("Restaurant Section", {"branch": BRANCH}, "name")
		cls.restaurant_admin = _make_user(RESTAURANT_ADMIN, "Restaurant Admin")
		frappe.db.commit()

	def setUp(self):
		super().setUp()
		# The class rolls back once, at the end — so an earlier test's deletion is
		# still in effect here, and the terminal needs its day back to sell.
		frappe.db.set_value("Branch", BRANCH, "company", self.company)
		_ensure_shift(self.profile)

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def _delete_transactions(self) -> None:
		"""What Company → Delete Transactions does first (`company.py`)."""
		record = frappe.get_doc({"doctype": "Transaction Deletion Record", "company": self.company})
		record.submit()
		# ERPNext refuses a second record while one is queued for the company, and
		# nothing here runs ERPNext's half to finish it — so it does not stay.
		frappe.db.delete("Transaction Deletion Record", {"name": record.name})

	def test_the_till_goes_with_the_books_and_the_setup_stays(self):
		order = self._order()
		log_audit(
			"cancel_order",
			branch=BRANCH,
			pos_profile=self.profile,
			restaurant_order=order.name,
			reason="probe",
		)
		setup = {doctype: frappe.db.count(doctype) for doctype in SETUP}

		self._delete_transactions()

		for doctype in (
			"Restaurant Order",
			"Restaurant Shift",
			"POS Audit Log",
			"POS Order Activity",
			"POS Order Counter",
		):
			self.assertEqual(frappe.db.count(doctype, {"branch": BRANCH}), 0, doctype)
		self.assertEqual(frappe.db.count("Restaurant Order Item", {"parent": order.name}), 0)
		self.assertEqual({doctype: frappe.db.count(doctype) for doctype in SETUP}, setup)
		self.assertIsNone(frappe.db.get_value("POS Profile", self.profile, "restaurant_shift"))

	def test_the_floor_is_handed_back_but_a_table_out_of_service_stays_out(self):
		# Any two in the branch: one section of the test site holds a single table,
		# and a test that skips on the site it runs on proves nothing.
		sections = frappe.get_all("Restaurant Section", filters={"branch": BRANCH}, pluck="name")
		tables = frappe.get_all(
			"Restaurant Table", filters={"section": ("in", sections)}, pluck="name", limit=2
		)
		self.assertEqual(len(tables), 2, "the test branch needs two tables")
		held, out_of_service = tables
		order = self._order()
		frappe.db.set_value("Restaurant Table", held, {"status": "occupied", "current_order": order.name})
		frappe.db.set_value("Restaurant Table", out_of_service, {"status": "inactive", "current_order": None})

		self._delete_transactions()

		self.assertEqual(
			frappe.db.get_value("Restaurant Table", held, ["status", "current_order"]), ("available", None)
		)
		self.assertEqual(frappe.db.get_value("Restaurant Table", out_of_service, "status"), "inactive")

	def test_a_replay_record_goes_with_its_order_and_a_customer_s_stays(self):
		"""A customer is not on ERPNext's list, so the replay that made one stays
		with it — or a retried "create customer" would make a second."""
		order = self._order()
		mine, customer = frappe.generate_hash(length=20), frappe.generate_hash(length=20)
		idempotency.remember(
			mine, "order.add_item", {}, reference_doctype="Restaurant Order", reference_name=order.name
		)
		idempotency.remember(
			customer, "create_customer", {}, reference_doctype="Customer", reference_name="x"
		)

		self._delete_transactions()

		self.assertFalse(frappe.db.exists("POS Sync Entry", {"queue_id": mine}))
		self.assertTrue(frappe.db.exists("POS Sync Entry", {"queue_id": customer}))

	def test_another_company_s_till_is_left_alone(self):
		"""One site, two companies: deleting one must not empty the other's till."""
		order = self._order()
		frappe.db.set_value("Branch", BRANCH, "company", "_RPOS Another Company")

		self._delete_transactions()

		self.assertTrue(frappe.db.exists("Restaurant Order", order.name))

	def test_only_a_system_manager_can_press_it(self):
		"""ERPNext's own rule, and the only thing between a Restaurant Admin and
		the till's whole history — so it is held here too."""
		order = self._order()
		frappe.set_user(self.restaurant_admin)

		with self.assertRaises(frappe.PermissionError):
			self._delete_transactions()

		frappe.set_user("Administrator")
		self.assertTrue(frappe.db.exists("Restaurant Order", order.name))

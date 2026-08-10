# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Discount ceilings and the manager override that lifts them.

Refs: BR-031, FR-10.4, FR-12.2
"""

import frappe
from frappe.utils import flt

from restaurant_pos.api import payment as payment_api
from restaurant_pos.api import permissions as permissions_api
from restaurant_pos.setup.defaults import create_default_data
from restaurant_pos.tests.test_payment import CASH, PaymentTestBase
from restaurant_pos.utils import manager_pin as pins
from restaurant_pos.utils import payment as service
from restaurant_pos.utils import permissions as perms

SENIOR = "rpos_discount_senior@example.com"
MANAGER = "rpos_discount_manager@example.com"


def _user(email: str, role: str, pin: str) -> str:
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"roles": [{"role": role}],
			}
		).insert(ignore_permissions=True)

	if not pins.has_pin(email):
		pins.set_pin(email, pin)

	return email


class TestDiscountOverride(PaymentTestBase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		create_default_data()
		# Senior cashier ceiling 10%, POS Manager 50% (08 §3).
		cls.senior = _user(SENIOR, "POS Senior Cashier", "3311")
		cls.manager = _user(MANAGER, "POS Manager", "7742")
		frappe.db.commit()

	def setUp(self):
		frappe.local.rpos_permission_cache = {}

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.rpos_permission_cache = {}

	# ------------------------------------------------------------- preview

	def test_preview_reports_the_total_without_touching_the_order(self):
		order = self._payable_order(qty=4)
		before = flt(order.total_amount)

		preview = payment_api.preview_totals(order.order_name, "percentage", 10)

		self.assertLess(preview["total_amount"], before)
		# Nothing was saved: the stored order is unchanged.
		self.assertEqual(
			flt(frappe.db.get_value("Restaurant Order", order.order_name, "total_amount")), before
		)

	def test_preview_flags_a_discount_the_cashier_cannot_apply(self):
		order = self._payable_order(qty=4)

		frappe.set_user(self.senior)
		frappe.local.rpos_permission_cache = {}
		try:
			within = payment_api.preview_totals(order.order_name, "percentage", 5)
			beyond = payment_api.preview_totals(order.order_name, "percentage", 40)
		finally:
			frappe.set_user("Administrator")

		self.assertFalse(within["requires_override"])
		self.assertTrue(beyond["requires_override"])
		self.assertEqual(beyond["max_discount_percentage"], 10)

	# ------------------------------------------------------------- ceilings

	def test_a_flat_amount_is_measured_against_the_percentage_ceiling(self):
		"""BR-031 — otherwise the cap is bypassed by entering riyals."""
		order = self._payable_order(qty=4)
		half_the_order = flt(order.subtotal) / 2

		self.assertAlmostEqual(service.discount_percentage(order, "amount", half_the_order), 50, places=1)

	def test_a_cashier_beyond_their_ceiling_is_refused(self):
		order = self._payable_order(qty=4)

		frappe.set_user(self.senior)
		frappe.local.rpos_permission_cache = {}
		try:
			with self.assertRaises(frappe.PermissionError):
				service.process_payment(
					order,
					payments=[{"method": CASH, "amount": flt(order.total_amount)}],
					discount_type="percentage",
					discount_value=40,
				)
		finally:
			frappe.set_user("Administrator")

	# ------------------------------------------------------------- override

	def test_an_approver_cannot_exceed_their_own_ceiling(self):
		"""The hole this change closed: 50% manager approving 90%."""
		self.assertEqual(perms.find_approver_for_discount("max_order_discount_pct", 40, "7742"), self.manager)
		self.assertIsNone(perms.find_approver_for_discount("max_order_discount_pct", 90, "7742"))

	def test_a_token_cannot_be_spent_on_a_bigger_discount(self):
		"""The second hole: an approval for 10% reused for 90%."""
		token = perms.issue_override_token(
			perms.discount_override_action("max_order_discount_pct", 10), self.manager
		)

		with self.assertRaises(frappe.PermissionError):
			perms.consume_override_token(token, perms.discount_override_action("max_order_discount_pct", 90))

	def test_a_wrong_pin_is_refused_and_logged(self):
		order = self._payable_order()

		with self.assertRaises(frappe.PermissionError):
			permissions_api.validate_discount_override(
				pin="0000",
				percentage=40,
				reason="Regular customer",
				branch=order.branch,
				pos_profile=order.pos_profile,
				order_name=order.order_name,
			)

		self.assertTrue(
			frappe.get_all(
				"POS Audit Log",
				filters={"restaurant_order": order.order_name, "action_type": "discount_override"},
			)
		)

	def test_an_approved_override_lets_the_discount_through_and_names_the_approver(self):
		order = self._payable_order(qty=4)

		frappe.set_user(self.senior)
		frappe.local.rpos_permission_cache = {}
		try:
			approval = permissions_api.validate_discount_override(
				pin="7742",
				percentage=40,
				reason="Complaint about the wait",
				branch=order.branch,
				pos_profile=order.pos_profile,
				order_name=order.order_name,
			)
			self.assertEqual(approval["approved_by"], self.manager)

			preview = payment_api.preview_totals(order.order_name, "percentage", 40)
			service.process_payment(
				order,
				payments=[{"method": CASH, "amount": preview["total_amount"]}],
				discount_type="percentage",
				discount_value=40,
				override_token=approval["override_token"],
			)
		finally:
			frappe.set_user("Administrator")

		order.reload()
		self.assertEqual(order.status, "closed")
		self.assertEqual(order.discount_approved_by, self.manager)
		# FR-12.7 — the approval is attributable to a person, not a role.

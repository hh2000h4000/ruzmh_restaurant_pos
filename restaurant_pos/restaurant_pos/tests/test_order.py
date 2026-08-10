# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Order lifecycle and money tests.

Refs: BR-010..BR-017, BR-024, BR-044, FR-2.1..FR-2.8, FR-10.4
"""

import uuid

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from restaurant_pos.restaurant_pos.api import order as api
from restaurant_pos.restaurant_pos.utils import order as service
from restaurant_pos.restaurant_pos.utils import totals

BRANCH = "Riyadh"
ITEM = "RPOS-TEST-BURGER"


CASHIER = "rpos_order_cashier@example.com"


def _make_cashier() -> str:
	"""A user with the shipped POS Cashier defaults — no price-change right."""
	from restaurant_pos.setup.defaults import create_default_data

	create_default_data()

	if not frappe.db.exists("User", CASHIER):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": CASHIER,
				"first_name": "RPOS Order Cashier",
				"send_welcome_email": 0,
				"roles": [{"role": "POS Cashier"}],
			}
		).insert(ignore_permissions=True)

	frappe.db.set_value("POS Permission Set", "POS Cashier", "can_change_item_price", 0)
	return CASHIER


def _ensure_shift(profile: str) -> str:
	shift = frappe.db.get_value("Restaurant Shift", {"branch": BRANCH, "status": "open"}, "name")
	if not shift:
		shift = (
			frappe.get_doc(
				{
					"doctype": "Restaurant Shift",
					"title": "RPOS Test Shift",
					"branch": BRANCH,
					"shift_date": now_datetime().date(),
					"shift_type": "full_day",
					"status": "open",
					"opened_by": "Administrator",
					"opened_at": now_datetime(),
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	frappe.db.set_value("POS Profile", profile, "restaurant_shift", shift)
	return shift


class OrderTestBase(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.profile = frappe.db.get_value("POS Profile", {}, "name")
		cls.section = frappe.db.get_value("POS Profile", cls.profile, "restaurant_section")
		cls.order_type = frappe.db.get_value("Restaurant Order Type", {"title": "Takeaway"}, "name")
		cls.dine_in = frappe.db.get_value("Restaurant Order Type", {"title": "Dine In"}, "name")
		cls.item = ITEM
		_ensure_shift(cls.profile)

		# A known price, so the assertions are about our arithmetic and not
		# about whether the site happens to have a price list configured.
		price_list = frappe.db.get_value("POS Profile", cls.profile, "selling_price_list")
		if not price_list:
			price_list = frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name")

		if not price_list:
			# install_fixtures() creates masters but not price lists; those come
			# from the setup wizard, which this test site never ran (D-012).
			price_list = (
				frappe.get_doc(
					{
						"doctype": "Price List",
						"price_list_name": "RPOS Test Selling",
						"currency": "SAR",
						"selling": 1,
						"enabled": 1,
					}
				)
				.insert(ignore_permissions=True)
				.name
			)

		frappe.db.set_value("POS Profile", cls.profile, "selling_price_list", price_list)

		cls.price_list = price_list
		if not frappe.db.exists("Item Price", {"item_code": ITEM, "price_list": price_list}):
			frappe.get_doc(
				{
					"doctype": "Item Price",
					"item_code": ITEM,
					"price_list": price_list,
					"selling": 1,
					"price_list_rate": 25,
				}
			).insert(ignore_permissions=True)

		frappe.db.commit()

	def _order(self, **kwargs):
		return service.create_order(
			order_type=kwargs.pop("order_type", self.order_type),
			pos_profile=self.profile,
			**kwargs,
		)


class TestOrderCreation(OrderTestBase):
	def test_a_new_order_starts_as_draft(self):
		order = self._order()
		self.assertEqual(order.status, "draft")
		self.assertEqual(order.cashier, frappe.session.user)
		self.assertEqual(order.branch, BRANCH)
		self.assertTrue(order.name.startswith("RO-"))

	def test_dine_in_requires_a_table(self):
		"""FR-2.1 / BR-064."""
		with self.assertRaises(frappe.ValidationError):
			self._order(order_type=self.dine_in, cover_count=2)

	def test_dine_in_requires_a_cover_count(self):
		table = frappe.db.get_value("Restaurant Table", {"section": self.section}, "name")
		frappe.db.set_value("Restaurant Table", table, "status", "available")

		with self.assertRaises(frappe.ValidationError):
			self._order(order_type=self.dine_in, table=table)

	def test_seating_a_table_marks_it_occupied(self):
		"""BR-061."""
		table = frappe.db.get_value("Restaurant Table", {"section": self.section}, "name")
		frappe.db.set_value("Restaurant Table", table, {"status": "available", "current_order": None})

		order = self._order(order_type=self.dine_in, table=table, cover_count=4)

		self.assertEqual(frappe.db.get_value("Restaurant Table", table, "status"), "occupied")
		self.assertEqual(frappe.db.get_value("Restaurant Table", table, "current_order"), order.name)

	def test_an_occupied_table_cannot_be_seated_again(self):
		table = frappe.db.get_value("Restaurant Table", {"section": self.section}, "name")
		frappe.db.set_value("Restaurant Table", table, "status", "occupied")

		with self.assertRaises(frappe.ValidationError):
			self._order(order_type=self.dine_in, table=table, cover_count=2)

	def test_delivery_requires_a_customer(self):
		delivery = frappe.db.get_value("Restaurant Order Type", {"title": "Delivery"}, "name")
		with self.assertRaises(frappe.ValidationError):
			self._order(order_type=delivery)

	def test_no_sales_without_an_open_shift(self):
		"""BR-044."""
		shift = frappe.db.get_value("POS Profile", self.profile, "restaurant_shift")
		frappe.db.set_value("Restaurant Shift", shift, "status", "closed")
		try:
			with self.assertRaises(frappe.ValidationError):
				self._order()
		finally:
			frappe.db.set_value("Restaurant Shift", shift, "status", "open")

	def test_an_inactive_order_type_is_refused(self):
		frappe.db.set_value("Restaurant Order Type", self.order_type, "is_active", 0)
		frappe.clear_cache(doctype="Restaurant Order Type")
		try:
			with self.assertRaises(frappe.ValidationError):
				self._order()
		finally:
			frappe.db.set_value("Restaurant Order Type", self.order_type, "is_active", 1)
			frappe.clear_cache(doctype="Restaurant Order Type")


class TestOrderItems(OrderTestBase):
	def test_adding_an_item_moves_draft_to_active(self):
		"""BR-011."""
		order = self._order()
		service.add_item(order, item=self.item, qty=1)
		self.assertEqual(order.status, "active")

	def test_the_price_comes_from_the_price_list(self):
		order = self._order()
		row = service.add_item(order, item=self.item, qty=1)
		self.assertEqual(row.rate, 25)

	def test_a_cashier_cannot_set_their_own_price(self):
		"""D-020 — the point of resolving the rate server-side.

		Runs as a cashier on purpose. As Administrator the override is
		legitimate, so asserting against the default test user would prove
		nothing.
		"""
		order = self._order()
		cashier = _make_cashier()

		frappe.set_user(cashier)
		frappe.local.rpos_permission_cache = {}
		try:
			with self.assertRaises(frappe.PermissionError):
				service.add_item(order, item=self.item, qty=1, rate=1)
		finally:
			frappe.set_user("Administrator")
			frappe.local.rpos_permission_cache = {}

	def test_a_permitted_price_override_is_audited(self):
		"""08 §5 — price_change leaves a trail naming who changed it."""
		order = self._order()
		service.add_item(order, item=self.item, qty=1, rate=30)

		entries = frappe.get_all(
			"POS Audit Log",
			filters={"restaurant_order": order.name, "action_type": "price_change"},
			fields=["details"],
		)
		self.assertTrue(entries)
		details = frappe.parse_json(entries[0].details)
		self.assertEqual(details["listed_rate"], 25)
		self.assertEqual(details["charged_rate"], 30)

	def test_quantity_must_be_positive(self):
		order = self._order()
		for bad in (0, -1):
			with self.assertRaises(frappe.ValidationError):
				service.add_item(order, item=self.item, qty=bad)

	def test_a_closed_order_cannot_be_changed(self):
		"""BR-017."""
		order = self._order()
		frappe.db.set_value("Restaurant Order", order.name, "status", "closed")
		order.reload()

		with self.assertRaises(frappe.ValidationError):
			service.add_item(order, item=self.item, qty=1)

	def test_routing_is_recorded_on_the_line(self):
		order = self._order()
		row = service.add_item(order, item=self.item, qty=1)
		self.assertIn("production_center", row.as_dict())


class TestVoidAndCancel(OrderTestBase):
	def test_voiding_needs_a_reason(self):
		order = self._order()
		service.add_item(order, item=self.item, qty=1)

		with self.assertRaises(frappe.ValidationError):
			service.void_item(order, item_idx=1, reason="  ")

	def test_voiding_removes_the_line_from_the_total(self):
		"""BR-013."""
		order = self._order()
		service.add_item(order, item=self.item, qty=2)
		before = order.subtotal

		service.void_item(order, item_idx=1, reason="Customer changed mind")

		self.assertEqual(before, 50)
		self.assertEqual(order.subtotal, 0)
		self.assertEqual(order.items[0].status, "void")
		self.assertEqual(order.items[0].voided_by, frappe.session.user)

	def test_voiding_a_sent_line_flags_a_void_kot(self):
		"""BR-013 — the kitchen must be told."""
		order = self._order()
		service.add_item(order, item=self.item, qty=1)
		order.items[0].status = "sent"
		order.save(ignore_permissions=True)

		outcome = service.void_item(order, item_idx=1, reason="Dropped")
		self.assertTrue(outcome["needs_void_kot"])

	def test_voiding_is_audited(self):
		order = self._order()
		service.add_item(order, item=self.item, qty=1)
		service.void_item(order, item_idx=1, reason="Wrong item")

		entry = frappe.get_all(
			"POS Audit Log",
			filters={"restaurant_order": order.name, "action_type": "void_item"},
			fields=["reason"],
		)
		self.assertTrue(entry)
		self.assertEqual(entry[0].reason, "Wrong item")

	def test_cancelling_needs_a_reason(self):
		order = self._order()
		with self.assertRaises(frappe.ValidationError):
			service.cancel_order(order, reason="")

	def test_cancelling_frees_the_table(self):
		"""BR-062."""
		table = frappe.db.get_value("Restaurant Table", {"section": self.section}, "name")
		frappe.db.set_value("Restaurant Table", table, {"status": "available", "current_order": None})
		order = self._order(order_type=self.dine_in, table=table, cover_count=2)

		service.cancel_order(order, reason="Customer left")

		self.assertEqual(order.status, "cancelled")
		self.assertEqual(frappe.db.get_value("Restaurant Table", table, "status"), "available")

	def test_a_paid_order_cannot_be_cancelled(self):
		"""BR-014 — use a return instead."""
		order = self._order()
		frappe.db.set_value("Restaurant Order", order.name, "status", "closed")
		order.reload()

		with self.assertRaises(frappe.ValidationError):
			service.cancel_order(order, reason="Mistake")

	def test_the_state_machine_refuses_impossible_moves(self):
		"""BR-010."""
		order = self._order()
		order.status = "closed"
		with self.assertRaises(frappe.ValidationError):
			service.assert_transition(order, "active")


class _StubOrder:
	"""A stand-in for a Restaurant Order document.

	Deliberately not ``frappe._dict``: that is a dict subclass, so ``.items``
	resolves to the dict method rather than the order lines and ``calculate``
	silently iterates nothing.
	"""

	def __init__(self, items, discount_type=None, discount_value=0):
		self.items = items
		self.discount_type = discount_type
		self.discount_value = discount_value
		self.pos_profile = None


class TestTotals(FrappeTestCase):
	"""FR-10.4 and BR-024."""

	def test_rounding_is_to_the_nearest_five_halalas(self):
		cases = {
			10.00: 10.00,
			10.01: 10.00,
			10.02: 10.00,
			10.03: 10.05,
			10.024: 10.00,
			10.025: 10.05,  # half rounds up, not to even
			47.13: 47.15,
			47.17: 47.15,
		}
		for raw, expected in cases.items():
			self.assertAlmostEqual(totals.round_to_step(raw), expected, places=2, msg=f"{raw}")

	def test_percentage_discount(self):
		self.assertEqual(totals.discount_amount(100, "percentage", 10), 10)

	def test_an_amount_discount_cannot_exceed_the_subtotal(self):
		self.assertEqual(totals.discount_amount(40, "amount", 100), 40)

	def test_a_percentage_over_100_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			totals.discount_amount(100, "percentage", 150)

	def test_discount_applies_before_tax(self):
		"""FR-10.4 — taxing before discounting over-collects VAT."""
		order = _StubOrder(
			[frappe._dict(amount=100, status="pending")],
			discount_type="percentage",
			discount_value=10,
		)

		original = totals.tax_rate_for
		totals.tax_rate_for = lambda _profile: 15.0
		try:
			totals.calculate(order)
		finally:
			totals.tax_rate_for = original

		self.assertEqual(order.subtotal, 100)
		self.assertEqual(order.discount_amount, 10)
		self.assertEqual(order.tax_amount, 13.5)  # 15% of 90, not of 100
		self.assertEqual(order.total_amount, 103.5)

	def test_voided_lines_are_excluded(self):
		order = _StubOrder(
			[
				frappe._dict(amount=25, status="pending"),
				frappe._dict(amount=25, status="void"),
			]
		)
		original = totals.tax_rate_for
		totals.tax_rate_for = lambda _p: 0.0
		try:
			totals.calculate(order)
		finally:
			totals.tax_rate_for = original

		self.assertEqual(order.subtotal, 25)


class TestIdempotency(OrderTestBase):
	"""09 §8 — a replayed queue_id must never create a second document."""

	def test_replaying_create_order_returns_the_same_order(self):
		queue_id = str(uuid.uuid4())

		first = api.create_order(order_type=self.order_type, pos_profile=self.profile, queue_id=queue_id)
		second = api.create_order(order_type=self.order_type, pos_profile=self.profile, queue_id=queue_id)

		self.assertEqual(first["order_name"], second["order_name"])
		self.assertTrue(second.get("already_processed"))
		self.assertEqual(
			frappe.db.count("Restaurant Order", {"offline_queue_id": queue_id}),
			1,
		)

	def test_replaying_add_item_does_not_duplicate_the_line(self):
		created = api.create_order(order_type=self.order_type, pos_profile=self.profile)
		queue_id = str(uuid.uuid4())

		api.add_item(created["order_name"], item=self.item, qty=1, queue_id=queue_id)
		api.add_item(created["order_name"], item=self.item, qty=1, queue_id=queue_id)

		order = frappe.get_doc("Restaurant Order", created["order_name"])
		self.assertEqual(len(order.items), 1)

	def test_two_different_queue_ids_both_apply(self):
		created = api.create_order(order_type=self.order_type, pos_profile=self.profile)

		api.add_item(created["order_name"], item=self.item, qty=1, queue_id=str(uuid.uuid4()))
		api.add_item(created["order_name"], item=self.item, qty=1, queue_id=str(uuid.uuid4()))

		order = frappe.get_doc("Restaurant Order", created["order_name"])
		self.assertEqual(len(order.items), 2)

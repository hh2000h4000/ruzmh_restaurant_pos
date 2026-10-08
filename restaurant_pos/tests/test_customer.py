# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Finding and creating a customer at the till.

The rule that carries the weight: **the mobile number is the key**. "محمد"
repeats a hundred times in any restaurant's database and a phone does not — and
a search that fails to recognise a number it has already seen creates a second
record for somebody who is already there, which is how a delivery history stops
being a history.

Refs: FR-2.1 step 4, FR-2.11, D-050
"""

import frappe

from restaurant_pos.api import order as order_api
from restaurant_pos.tests.test_order import OrderTestBase
from restaurant_pos.utils import customer as service
from restaurant_pos.utils import order as orders

PHONE = "0501234567"
NAME = "حمزة التجريبي"


class CustomerTestBase(OrderTestBase):
	def setUp(self):
		self._forget()

	def tearDown(self):
		self._forget()

	def _forget(self) -> None:
		"""Leave no test customer behind for the duplicate check to trip on."""
		for name in frappe.get_all(
			"Customer", filters={"customer_name": ("like", "%التجريبي%")}, pluck="name"
		):
			for contact in frappe.get_all(
				"Dynamic Link",
				filters={"link_doctype": "Customer", "link_name": name, "parenttype": "Contact"},
				pluck="parent",
			):
				frappe.delete_doc("Contact", contact, force=True, ignore_permissions=True)

			for address in frappe.get_all(
				"Dynamic Link",
				filters={"link_doctype": "Customer", "link_name": name, "parenttype": "Address"},
				pluck="parent",
			):
				frappe.delete_doc("Address", address, force=True, ignore_permissions=True)

			frappe.delete_doc("Customer", name, force=True, ignore_permissions=True)

		frappe.db.commit()


class TestTheNumberIsTheKey(CustomerTestBase):
	def test_a_number_typed_three_ways_finds_one_person(self):
		"""0501234567, +966501234567 and 966501234567 are the same customer."""
		service.create(phone=PHONE, customer_name=NAME)

		for typed in ("0501234567", "+966501234567", "966501234567", "050 123 4567"):
			found = service.search(phone=typed)
			self.assertEqual(len(found), 1, typed)
			self.assertEqual(found[0]["customer_name"], NAME, typed)

	def test_it_is_found_while_the_number_is_still_being_typed(self):
		"""`D-339` — «0501» said "no such customer" and offered to create them again."""
		service.create(phone=PHONE, customer_name=NAME)

		for typed in ("0501", "050123", "1234567"):
			self.assertIn(NAME, [row["customer_name"] for row in service.search(phone=typed)], typed)

	def test_the_number_is_stored_where_erpnext_keeps_it(self):
		"""D-050 — findable at all depends on the contact being made and linked."""
		created = service.create(phone=PHONE, customer_name=NAME)

		contact = frappe.db.get_value("Customer", created["name"], "customer_primary_contact")
		self.assertTrue(contact, "no primary contact, so the number is unreachable")
		self.assertEqual(frappe.db.get_value("Contact Phone", {"parent": contact}, "phone"), PHONE)

	def test_a_second_customer_on_one_number_is_refused(self):
		"""Two records on one phone is how a history splits in half."""
		service.create(phone=PHONE, customer_name=NAME)

		with self.assertRaises(frappe.DuplicateEntryError):
			service.create(phone="+966501234567", customer_name="شخص آخر التجريبي")

	def test_a_missing_number_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			service.create(phone="", customer_name=NAME)

	def test_a_missing_name_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			service.create(phone=PHONE, customer_name="  ")

	def test_a_name_search_is_the_fallback_and_not_the_key(self):
		service.create(phone=PHONE, customer_name=NAME)

		self.assertTrue(service.search(name="التجريبي"))
		self.assertFalse(service.search(name="لا أحد بهذا الاسم"))


class TestAddresses(CustomerTestBase):
	def test_the_first_address_becomes_the_primary(self):
		created = service.create(
			phone=PHONE, customer_name=NAME, address={"address_line1": "شارع الملك فهد", "city": "الرياض"}
		)

		self.assertEqual(len(created["addresses"]), 1)
		self.assertEqual(
			frappe.db.get_value("Customer", created["name"], "customer_primary_address"),
			created["addresses"][0]["name"],
		)

	def test_a_customer_may_have_several(self):
		"""A person has a home and a work, and delivery picks between them."""
		created = service.create(phone=PHONE, customer_name=NAME, address={"address_line1": "البيت"})
		service.add_address(created["name"], {"address_line1": "المكتب"})

		self.assertEqual(len(service.addresses_of(created["name"])), 2)

	def test_an_address_needs_a_line(self):
		created = service.create(phone=PHONE, customer_name=NAME)

		with self.assertRaises(frappe.ValidationError):
			service.add_address(created["name"], {"city": "الرياض"})


class TestAttachingToAnOrder(CustomerTestBase):
	def test_a_customer_is_attached_after_the_order_opened(self):
		"""The cashier rings items first and asks for the number after."""
		created = service.create(phone=PHONE, customer_name=NAME)
		order = self._order()

		orders.set_customer(order, customer=created["name"])

		self.assertEqual(order.customer, created["name"])

	def test_the_address_must_belong_to_that_customer(self):
		"""Otherwise it is either a mistake or a way to read a stranger's home."""
		mine = service.create(phone=PHONE, customer_name=NAME)
		theirs = service.create(
			phone="0559999999", customer_name="جار التجريبي", address={"address_line1": "بيت الجار"}
		)

		order = self._order()
		with self.assertRaises(frappe.ValidationError):
			orders.set_customer(order, customer=mine["name"], delivery_address=theirs["addresses"][0]["name"])

	def test_its_own_address_is_accepted(self):
		created = service.create(phone=PHONE, customer_name=NAME, address={"address_line1": "شارع الملك فهد"})
		order = self._order()

		orders.set_customer(order, customer=created["name"], delivery_address=created["addresses"][0]["name"])

		self.assertEqual(order.delivery_address, created["addresses"][0]["name"])

	def test_clearing_the_customer_clears_the_address(self):
		"""An address with nobody attached to it is a delivery to nowhere."""
		created = service.create(phone=PHONE, customer_name=NAME, address={"address_line1": "شارع الملك فهد"})
		order = self._order()
		orders.set_customer(order, customer=created["name"], delivery_address=created["addresses"][0]["name"])

		orders.set_customer(order, customer=None)

		self.assertIsNone(order.customer)
		self.assertIsNone(order.delivery_address)

	def test_the_bill_names_the_address_rather_than_its_id(self):
		"""A driver cannot read `ADDR-00012`, and the screen shows one line."""
		created = service.create(
			phone=PHONE,
			customer_name=NAME,
			address={"address_line1": "شارع الملك فهد", "city": "الرياض"},
		)
		order = self._order()
		address = created["addresses"][0]["name"]
		orders.set_customer(order, customer=created["name"], delivery_address=address)

		line = order_api.get_order(order.name)["delivery_address_line"]

		self.assertIn("شارع الملك فهد", line)
		self.assertIn("الرياض", line)

	def test_an_order_going_nowhere_says_nothing(self):
		self.assertIsNone(order_api.get_order(self._order().name)["delivery_address_line"])

	def test_a_type_that_needs_a_customer_refuses_to_lose_one(self):
		"""FR-2.1 — the requirement does not lapse once the order is open."""
		delivery = frappe.db.get_value("Restaurant Order Type", {"title": "Delivery"}, "name")
		created = service.create(phone=PHONE, customer_name=NAME)

		order = self._order(customer=created["name"])
		frappe.db.set_value("Restaurant Order", order.name, "order_type", delivery)
		order.reload()

		with self.assertRaises(frappe.ValidationError):
			orders.set_customer(order, customer=None)

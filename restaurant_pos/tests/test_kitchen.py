# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""KOT generation tests.

Refs: BR-013, BR-073, BR-074, BR-075, FR-2.3, FR-2.4, FR-2.5, FR-6.3, FR-6.4
"""

import uuid

import frappe

from restaurant_pos.api import kitchen as api
from restaurant_pos.tests.test_order import ITEM, OrderTestBase
from restaurant_pos.utils import kitchen as service
from restaurant_pos.utils import order as orders

ITEM_DRINK = "RPOS-TEST-FRIES"


class KitchenTestBase(OrderTestBase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.grill = frappe.db.get_value("Production Center", {"title": "RPOS Test Grill"}, "name")
		cls.fryer = frappe.db.get_value("Production Center", {"title": "RPOS Test Fryer"}, "name")

		if not frappe.db.exists("Item Price", {"item_code": ITEM_DRINK, "price_list": cls.price_list}):
			frappe.get_doc(
				{
					"doctype": "Item Price",
					"item_code": ITEM_DRINK,
					"price_list": cls.price_list,
					"selling": 1,
					"price_list_rate": 8,
				}
			).insert(ignore_permissions=True)

		frappe.db.commit()

	def _order_with(self, *items):
		order = self._order()
		for item, center in items:
			row = orders.add_item(order, item=item, qty=1)
			row.production_center = center
		order.save(ignore_permissions=True)
		return order


class TestSendToKitchen(KitchenTestBase):
	def test_the_first_send_is_an_initial_kot(self):
		"""BR-073."""
		order = self._order_with((ITEM, self.grill))
		result = service.send_to_kitchen(order)

		self.assertEqual(len(result["kots_created"]), 1)
		self.assertEqual(result["kots_created"][0]["kot_type"], "initial")

	def test_sending_moves_the_order_into_the_kitchen(self):
		"""FR-2.3."""
		order = self._order_with((ITEM, self.grill))
		service.send_to_kitchen(order)

		self.assertEqual(order.status, "in_kitchen")
		self.assertEqual(order.items[0].status, "sent")
		self.assertIsNotNone(order.items[0].sent_at)
		self.assertIsNotNone(order.items[0].kot_reference)

	def test_one_kot_per_production_center(self):
		"""FR-6.3 — three items, two stations, two tickets."""
		order = self._order_with((ITEM, self.grill), (ITEM_DRINK, self.fryer), (ITEM, self.grill))
		result = service.send_to_kitchen(order)

		centers = {kot["production_center"] for kot in result["kots_created"]}
		self.assertEqual(centers, {self.grill, self.fryer})

		grill_kot = frappe.get_doc(
			"Kitchen Order Ticket",
			next(k["kot_name"] for k in result["kots_created"] if k["production_center"] == self.grill),
		)
		self.assertEqual(len(grill_kot.items), 2)

	def test_a_later_send_is_an_addition_with_only_the_new_lines(self):
		"""FR-2.4 — the kitchen must not receive the first items twice."""
		order = self._order_with((ITEM, self.grill))
		service.send_to_kitchen(order)

		row = orders.add_item(order, item=ITEM_DRINK, qty=2)
		row.production_center = self.fryer
		order.save(ignore_permissions=True)

		result = service.send_to_kitchen(order)

		self.assertEqual(len(result["kots_created"]), 1)
		self.assertEqual(result["kots_created"][0]["kot_type"], "addition")

		kot = frappe.get_doc("Kitchen Order Ticket", result["kots_created"][0]["kot_name"])
		self.assertEqual(len(kot.items), 1)
		self.assertEqual(kot.items[0].item, ITEM_DRINK)

	def test_sending_twice_with_nothing_new_is_refused(self):
		order = self._order_with((ITEM, self.grill))
		service.send_to_kitchen(order)

		with self.assertRaises(frappe.ValidationError):
			service.send_to_kitchen(order)

	def test_the_header_identifies_the_ticket(self):
		"""BR-074 — order, table, order type, cashier, timestamp."""
		order = self._order_with((ITEM, self.grill))
		result = service.send_to_kitchen(order)
		kot = frappe.get_doc("Kitchen Order Ticket", result["kots_created"][0]["kot_name"])

		self.assertEqual(kot.restaurant_order, order.name)
		self.assertTrue(kot.order_type_title)
		self.assertTrue(kot.cashier_name)
		self.assertIsNotNone(kot.sent_at)

	def test_a_kot_carries_no_prices(self):
		"""BR-075 — the kitchen never sees money."""
		order = self._order_with((ITEM, self.grill))
		result = service.send_to_kitchen(order)
		kot = frappe.get_doc("Kitchen Order Ticket", result["kots_created"][0]["kot_name"])

		row_fields = set(kot.items[0].as_dict())
		for money_field in ("rate", "amount", "price", "price_list_rate"):
			self.assertNotIn(money_field, row_fields)

	def test_an_unrouted_item_is_reported_not_swallowed(self):
		"""BR-070 level 7 — an item no station cooks must be visible."""
		order = self._order()
		row = orders.add_item(order, item=ITEM, qty=1)
		row.production_center = None
		order.save(ignore_permissions=True)

		result = service.send_to_kitchen(order)

		self.assertEqual(result["kots_created"], [])
		self.assertEqual(len(result["unrouted_items"]), 1)
		self.assertEqual(order.items[0].status, "sent")

	def test_kots_start_unprinted(self):
		"""Printing is Phase 3; the ticket waits at pending."""
		order = self._order_with((ITEM, self.grill))
		result = service.send_to_kitchen(order)
		self.assertEqual(result["kots_created"][0]["print_status"], "pending")


class TestVoidKot(KitchenTestBase):
	def test_voiding_a_sent_line_raises_a_void_kot(self):
		"""BR-013 — the gap left open by the order slice, now closed."""
		order = self._order_with((ITEM, self.grill))
		service.send_to_kitchen(order)

		outcome = orders.void_item(order, item_idx=1, reason="Dropped on the floor")

		self.assertEqual(len(outcome["void_kots"]), 1)
		kot = frappe.get_doc("Kitchen Order Ticket", outcome["void_kots"][0]["kot_name"])
		self.assertEqual(kot.kot_type, "void")
		self.assertEqual(kot.items[0].action, "void")
		self.assertEqual(kot.production_center, self.grill)

	def test_voiding_an_unsent_line_raises_nothing(self):
		"""The kitchen never saw it, so there is nothing to withdraw."""
		order = self._order_with((ITEM, self.grill))
		outcome = orders.void_item(order, item_idx=1, reason="Changed mind")
		self.assertEqual(outcome["void_kots"], [])

	def test_cancelling_withdraws_every_sent_line(self):
		"""FR-2.8."""
		order = self._order_with((ITEM, self.grill), (ITEM_DRINK, self.fryer))
		service.send_to_kitchen(order)

		outcome = orders.cancel_order(order, reason="Customer left")

		centers = {kot["production_center"] for kot in outcome["void_kots"]}
		self.assertEqual(centers, {self.grill, self.fryer})

	def test_cancelling_before_sending_withdraws_nothing(self):
		order = self._order_with((ITEM, self.grill))
		outcome = orders.cancel_order(order, reason="Mistake")
		self.assertEqual(outcome["void_kots"], [])


class TestReprint(KitchenTestBase):
	def test_reprint_does_not_duplicate_the_ticket(self):
		"""D-021 — a reprint is the same ticket twice on paper."""
		order = self._order_with((ITEM, self.grill))
		result = service.send_to_kitchen(order)
		kot_name = result["kots_created"][0]["kot_name"]

		before = frappe.db.count("Kitchen Order Ticket", {"restaurant_order": order.name})
		service.reprint(kot_name)
		after = frappe.db.count("Kitchen Order Ticket", {"restaurant_order": order.name})

		self.assertEqual(before, after)

	def test_reprint_requeues_and_is_audited(self):
		"""FR-6.4."""
		order = self._order_with((ITEM, self.grill))
		result = service.send_to_kitchen(order)
		kot_name = result["kots_created"][0]["kot_name"]
		frappe.db.set_value("Kitchen Order Ticket", kot_name, "print_status", "printed")

		service.reprint(kot_name)

		self.assertEqual(frappe.db.get_value("Kitchen Order Ticket", kot_name, "print_status"), "pending")
		self.assertTrue(
			frappe.get_all(
				"POS Audit Log",
				filters={"restaurant_order": order.name, "action_type": "reprint_receipt"},
			)
		)


class TestKitchenIdempotency(KitchenTestBase):
	def test_replaying_send_to_kitchen_creates_no_second_ticket(self):
		"""09 §8 — a retry after a dropped connection must not double the order."""
		order = self._order_with((ITEM, self.grill))
		queue_id = str(uuid.uuid4())

		api.send_to_kitchen(order.name, queue_id=queue_id)
		api.send_to_kitchen(order.name, queue_id=queue_id)

		self.assertEqual(frappe.db.count("Kitchen Order Ticket", {"restaurant_order": order.name}), 1)


class TestOrderNoteReachesEveryStation(KitchenTestBase):
	"""FR-2.9 — the case an item note cannot cover.

	An item note travels with its line to the one station that cooks it. An
	allergy, or "rush this", has to reach them all — and reaching only the grill
	is the failure this note exists to prevent.
	"""

	def test_every_station_gets_it(self):
		"""Two stations, one note, printed on both tickets."""
		order = self._order_with((ITEM, self.grill), (ITEM_DRINK, self.fryer))
		orders.set_order_notes(order, notes="حساسية — بدون فول سوداني")

		service.send_to_kitchen(order)

		tickets = frappe.get_all(
			"Kitchen Order Ticket",
			filters={"restaurant_order": order.name},
			fields=["production_center", "order_notes"],
		)
		self.assertEqual(len(tickets), 2, "expected one ticket per station")
		for ticket in tickets:
			self.assertEqual(ticket.order_notes, "حساسية — بدون فول سوداني", ticket.production_center)

	def test_a_note_added_afterwards_reaches_a_ticket_already_sent(self):
		"""The customer says "make it quick" after ordering, which is the norm."""
		order = self._order_with((ITEM, self.grill), (ITEM_DRINK, self.fryer))
		service.send_to_kitchen(order)

		orders.set_order_notes(order, notes="مستعجل")

		notes = frappe.get_all(
			"Kitchen Order Ticket",
			filters={"restaurant_order": order.name, "kot_type": ("!=", "void")},
			pluck="order_notes",
		)
		self.assertTrue(notes)
		self.assertTrue(all(note == "مستعجل" for note in notes), notes)

	def test_clearing_the_note_clears_it_on_the_ticket(self):
		order = self._order_with((ITEM, self.grill))
		orders.set_order_notes(order, notes="مستعجل")
		service.send_to_kitchen(order)

		orders.set_order_notes(order, notes="")

		self.assertIsNone(order.notes)
		notes = frappe.get_all(
			"Kitchen Order Ticket",
			filters={"restaurant_order": order.name, "kot_type": ("!=", "void")},
			pluck="order_notes",
		)
		self.assertTrue(all(not note for note in notes), notes)

	def test_an_item_note_stays_on_its_own_line(self):
		"""The two scopes are not interchangeable.

		The line note goes to the grill's ticket and nowhere else; the fryer's
		ticket carries its own line, with no note.
		"""
		order = self._order()
		row = orders.add_item(order, item=ITEM, qty=1, notes="بدون بصل")
		row.production_center = self.grill
		other = orders.add_item(order, item=ITEM_DRINK, qty=1)
		other.production_center = self.fryer
		order.save(ignore_permissions=True)

		service.send_to_kitchen(order)

		seen = {}
		for ticket in frappe.get_all(
			"Kitchen Order Ticket",
			filters={"restaurant_order": order.name},
			fields=["name", "production_center"],
		):
			rows = frappe.get_all("KOT Item", filters={"parent": ticket.name}, fields=["item", "notes"])
			seen[ticket.production_center] = {row.item: row.notes for row in rows}

		self.assertEqual(seen[self.grill][ITEM], "بدون بصل")
		self.assertIsNone(seen[self.fryer][ITEM_DRINK])


class TestItemNotesAreAlwaysReachable(KitchenTestBase):
	"""FR-2.9 — every line takes a note, whatever the item and whenever asked.

	A note used to be reachable only through the modifier popup, which opens
	only for items that have modifier groups: a plain dish could never be given
	one at all.
	"""

	def test_a_plain_item_takes_a_note(self):
		order = self._order()
		orders.add_item(order, item=ITEM, qty=1)

		orders.set_item_notes(order, item_idx=1, notes="بدون بصل")

		self.assertEqual(order.items[0].notes, "بدون بصل")

	def test_a_note_after_the_kitchen_has_the_line_corrects_the_ticket(self):
		"""'Actually, no onion' is the commonest thing said once the order is in."""
		order = self._order_with((ITEM, self.grill))
		service.send_to_kitchen(order)

		orders.set_item_notes(order, item_idx=1, notes="بدون بصل")

		row = frappe.get_all(
			"KOT Item",
			filters={"parent": order.items[0].kot_reference, "item": ITEM},
			fields=["notes"],
		)
		self.assertTrue(row)
		self.assertEqual(row[0].notes, "بدون بصل")

	def test_no_second_ticket_is_made(self):
		"""BR-073 — a duplicate ticket is how a kitchen cooks an order twice."""
		order = self._order_with((ITEM, self.grill))
		service.send_to_kitchen(order)
		before = frappe.db.count("Kitchen Order Ticket", {"restaurant_order": order.name})

		orders.set_item_notes(order, item_idx=1, notes="بدون بصل")

		self.assertEqual(frappe.db.count("Kitchen Order Ticket", {"restaurant_order": order.name}), before)

	def test_clearing_it_clears_the_ticket_too(self):
		order = self._order_with((ITEM, self.grill))
		orders.set_item_notes(order, item_idx=1, notes="بدون بصل")
		service.send_to_kitchen(order)

		orders.set_item_notes(order, item_idx=1, notes="")

		self.assertIsNone(order.items[0].notes)
		row = frappe.get_all(
			"KOT Item", filters={"parent": order.items[0].kot_reference, "item": ITEM}, fields=["notes"]
		)
		self.assertIsNone(row[0].notes)

	def test_a_voided_line_is_refused(self):
		order = self._order_with((ITEM, self.grill))
		orders.void_item(order, item_idx=1, reason="test")

		with self.assertRaises(frappe.ValidationError):
			orders.set_item_notes(order, item_idx=1, notes="بدون بصل")

	def test_an_unknown_row_is_refused(self):
		order = self._order_with((ITEM, self.grill))

		with self.assertRaises(frappe.ValidationError):
			orders.set_item_notes(order, item_idx=99, notes="بدون بصل")

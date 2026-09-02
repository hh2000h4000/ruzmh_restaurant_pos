# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The story of a bill.

Refs: FR-12.7, D-106
"""

import frappe

from restaurant_pos.api import activity as api
from restaurant_pos.tests.test_order import ITEM, OrderTestBase
from restaurant_pos.utils import activity as service
from restaurant_pos.utils import order as orders


class ActivityTestBase(OrderTestBase):
	def _actions(self, order_name: str) -> list[str]:
		return [row.action for row in service.timeline(order_name)]


class TestWhatIsRecorded(ActivityTestBase):
	def test_opening_a_bill_is_the_first_entry(self):
		order = self._order()

		self.assertEqual(self._actions(order.name)[0], "opened")

	def test_adding_an_item_names_it(self):
		order = self._order()
		orders.add_item(order, item=ITEM, qty=2)

		entry = service.timeline(order.name)[-1]

		self.assertEqual(entry.action, "item_added")
		self.assertIn("2", entry.subject)
		self.assertEqual(entry.details["qty"], 2)

	def test_changing_a_quantity_records_both_numbers(self):
		"""'Changed the quantity' answers nothing; from what, to what, does."""
		order = self._order()
		orders.add_item(order, item=ITEM, qty=1)
		order.reload()
		orders.set_item_qty(order, item_idx=1, qty=3)

		entry = service.timeline(order.name)[-1]

		self.assertEqual(entry.action, "item_qty_changed")
		self.assertEqual(entry.details["from"], 1)
		self.assertEqual(entry.details["to"], 3)

	def test_removing_an_item_keeps_its_name(self):
		"""The row is gone; the record of what it was must not be."""
		order = self._order()
		orders.add_item(order, item=ITEM, qty=1)
		order.reload()
		orders.remove_item(order, item_idx=1)

		entry = service.timeline(order.name)[-1]

		self.assertEqual(entry.action, "item_removed")
		self.assertTrue(entry.subject)

	def test_every_entry_names_who_did_it(self):
		"""The whole point (`D-094` is what makes it a person, not a terminal)."""
		order = self._order()
		orders.add_item(order, item=ITEM, qty=1)

		for row in service.timeline(order.name):
			self.assertEqual(row.user, frappe.session.user)

	def test_the_story_reads_in_the_order_it_happened(self):
		order = self._order()
		orders.add_item(order, item=ITEM, qty=1)
		order.reload()
		orders.set_item_qty(order, item_idx=1, qty=2)

		self.assertEqual(self._actions(order.name), ["opened", "item_added", "item_qty_changed"])


class TestItNeverCostsTheBill(ActivityTestBase):
	"""A bill's history is worth having and never worth losing the bill for.

	If a write here can raise, a cashier cannot serve a customer because of a
	bookkeeping table — the wrong trade in every restaurant. So the guard is
	inside `log` itself, and these press on it from the outside rather than
	replacing it: a test that patched `log` away would be testing the patch.
	"""

	def test_an_order_that_does_not_exist_returns_none(self):
		self.assertIsNone(service.log("RO-does-not-exist", "viewed"))

	def test_an_action_the_doctype_rejects_returns_none(self):
		"""An insert that fails is swallowed, not raised at the till."""
		order = self._order()

		self.assertIsNone(service.log(order, "not-a-real-action"))

	def test_and_the_bill_is_untouched_by_that_failure(self):
		order = self._order()
		service.log(order, "not-a-real-action")

		row = orders.add_item(order, item=ITEM, qty=1)

		self.assertTrue(row.name)


class TestTheScreensOwnTwoEvents(ActivityTestBase):
	def test_a_cashier_opening_a_held_bill_is_recorded(self):
		"""Nothing changes, so nothing else would ever know it happened."""
		order = self._order()

		api.record_view(order_name=order.name, action="viewed")

		self.assertIn("viewed", self._actions(order.name))

	def test_a_screen_cannot_write_whatever_it_likes(self):
		"""This endpoint is reachable from a till."""
		order = self._order()

		with self.assertRaises(frappe.ValidationError):
			api.record_view(order_name=order.name, action="paid")


class TestSensitiveActionsAppearInBoth(ActivityTestBase):
	def test_a_void_is_on_the_timeline_and_carries_its_audit_entry(self):
		"""One call site, two records (`D-106`).

		A manager reading a bill's story must see the void in it; an auditor
		reading the compliance log must see it there. Writing it from `log_audit`
		is what stops one of the two being forgotten at a call site.
		"""
		order = self._order()
		orders.add_item(order, item=ITEM, qty=1)
		order.reload()
		from restaurant_pos.utils import kitchen

		kitchen.send_to_kitchen(order)
		order.reload()

		orders.void_item(order, item_idx=1, reason="Dropped on the floor")

		voided = [row for row in service.timeline(order.name) if row.action == "item_voided"]

		self.assertEqual(len(voided), 1)
		self.assertTrue(voided[0].audit_log, "the timeline entry must point at the audit entry")
		self.assertTrue(frappe.db.exists("POS Audit Log", voided[0].audit_log))


class TestPruning(ActivityTestBase):
	def test_old_entries_go_and_recent_ones_stay(self):
		from frappe.utils import add_days, now_datetime

		order = self._order()
		old = service.timeline(order.name)[0].name
		frappe.db.set_value(
			"POS Order Activity", old, "at", add_days(now_datetime(), -(service.KEEP_DAYS + 5))
		)

		fresh = service.log(order, "viewed")
		service.prune(service.KEEP_DAYS)

		self.assertFalse(frappe.db.exists("POS Order Activity", old))
		self.assertTrue(frappe.db.exists("POS Order Activity", fresh))

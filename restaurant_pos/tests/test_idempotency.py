# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Forgetting old replays without forgetting one that can still land.

Refs: 09 §8, D-019, D-206
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime

from restaurant_pos.utils import idempotency


class TestPruningTheReplayLedger(FrappeTestCase):
	def _entry_aged(self, days: int) -> str:
		queue_id = frappe.generate_hash(length=32)
		idempotency.remember(queue_id, "order.add_item", {"ok": True})
		frappe.db.set_value(
			"POS Sync Entry",
			{"queue_id": queue_id},
			"creation",
			add_days(now_datetime(), -days),
			update_modified=False,
		)
		return queue_id

	def test_an_entry_past_the_window_is_forgotten(self):
		old = self._entry_aged(idempotency.KEEP_DAYS + 1)

		idempotency.prune()

		self.assertFalse(frappe.db.exists("POS Sync Entry", {"queue_id": old}))

	def test_an_entry_inside_the_window_still_answers_a_replay(self):
		"""The other side of the line — and the one that costs money if wrong.

		**Twenty-nine days as a number, not `KEEP_DAYS - 1`.** Measured against
		the constant, the age moves with it: the mutation shortening the window
		to the 72 hours `D-019` first named aged this row two days, kept it, and
		passed. What is promised is a month, so the test says a month.
		"""
		recent = self._entry_aged(29)

		idempotency.prune()

		self.assertTrue(idempotency.previous_result(recent)["already_processed"])

	def test_it_runs_every_day(self):
		"""A prune nothing schedules is a table that grows anyway."""
		self.assertIn(
			"restaurant_pos.utils.idempotency.prune",
			frappe.get_hooks("scheduler_events").get("daily", []),
		)

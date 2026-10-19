# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""A print job is queued only when there is paper for it (`D-364`).

The load test queued two jobs a sale in a branch with no printer at all — each
found out only when it ran — and 737 of them stood in front of the day's
posting. The question «is there paper?» is asked before the job now.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant_pos.tests.test_order import BRANCH
from restaurant_pos.tests.test_printer_branch import _other_branch
from restaurant_pos.utils import kitchen, printing


def _ticket(production_center=None):
	return frappe._dict(name="KOT-TEST", production_center=production_center)


class PaperIsAskedForBeforeTheJob(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.bare = _other_branch()
		for station in frappe.get_all("Production Center", filters={"branch": self.bare}, pluck="name"):
			frappe.db.set_value("Production Center", station, "is_active", 0)
		self.profile = frappe.db.get_value("POS Profile", {"default_printer": ("is", "set")}, "name")

	def test_a_branch_with_no_kitchen_prints_no_ticket(self):
		"""A counter or a café: nothing is assumed, no job is made."""
		self.assertFalse(kitchen.has_kitchen(self.bare))
		self.assertFalse(kitchen.prints_on_send(None, self.bare))

		with (
			patch.object(printing, "enqueue_print") as queued,
			patch.object(printing, "mark_kot_failed") as failed,
		):
			kitchen.queue_paper(_ticket(), frappe._dict(branch=self.bare, pos_profile=self.profile))

		queued.assert_not_called()
		failed.assert_not_called()

	def test_a_branch_with_a_kitchen_still_prints_what_nobody_routed(self):
		"""`D-300` stands where there is a kitchen: the slip in the setup still reaches the cook."""
		if not kitchen.has_kitchen(BRANCH):
			self.skipTest("the test branch has no station")
		if not self.profile:
			self.skipTest("no terminal with a printer")

		with patch.object(printing, "enqueue_print") as queued:
			kitchen.queue_paper(_ticket(), frappe._dict(branch=BRANCH, pos_profile=self.profile))

		queued.assert_called_once()

	def test_a_ticket_that_wants_paper_and_has_no_printer_fails_without_a_job(self):
		with (
			patch.object(printing, "kot_printer", return_value=None),
			patch.object(printing, "enqueue_print") as queued,
			patch.object(printing, "mark_kot_failed") as failed,
		):
			kitchen.queue_paper(_ticket(), frappe._dict(branch=BRANCH, pos_profile=None), force=True)

		queued.assert_not_called()
		failed.assert_called_once_with("KOT-TEST")

	def test_a_receipt_is_queued_only_where_there_is_a_printer(self):
		with patch.object(printing, "enqueue_print") as queued:
			with patch.object(printing, "receipt_printer", return_value=None):
				printing.queue_receipt("INV", order_name=None, pos_profile="T")
			queued.assert_not_called()

			with patch.object(printing, "receipt_printer", return_value="PRT"):
				printing.queue_receipt("INV", order_name=None, pos_profile="T")
			queued.assert_called_once()

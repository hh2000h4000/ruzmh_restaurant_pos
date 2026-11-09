# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""A till write that loses a deadlock is run once more (`D-369`)."""

import ast
import pathlib
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant_pos.utils.deadlock import OrderBusy, retried

API = pathlib.Path(__file__).resolve().parent.parent / "api"


class EveryTillWriteRetries(FrappeTestCase):
	def test_every_endpoint_that_takes_a_queue_id_is_retried(self):
		"""The till's writes are the ones two tills make at once; a new one cannot forget."""
		missing = []
		for path in sorted(API.glob("*.py")):
			tree = ast.parse(path.read_text(encoding="utf-8"))
			for node in tree.body:
				if not isinstance(node, ast.FunctionDef):
					continue
				if not any(arg.arg == "queue_id" for arg in node.args.args + node.args.kwonlyargs):
					continue
				if not any(isinstance(d, ast.Name) and d.id == "retried" for d in node.decorator_list):
					missing.append(f"{path.stem}.{node.name}")
		self.assertEqual(missing, [])


class ALostDeadlockIsRunAgain(FrappeTestCase):
	def test_it_runs_again_once_and_answers(self):
		calls = []

		@retried
		def write():
			calls.append(1)
			if len(calls) == 1:
				raise frappe.QueryDeadlockError("1213")
			return "done"

		with patch.object(frappe.db, "rollback") as rolled_back, patch("time.sleep"):
			self.assertEqual(write(), "done")

		self.assertEqual(len(calls), 2)
		rolled_back.assert_called_once()

	def test_a_second_deadlock_is_raised(self):
		@retried
		def write():
			raise frappe.QueryDeadlockError("1213")

		with patch.object(frappe.db, "rollback"), patch("time.sleep"):
			with self.assertRaises(frappe.QueryDeadlockError):
				write()

	def test_a_lock_held_past_the_wait_is_said_in_words_and_kept_for_the_queue(self):
		"""`D-429` — not "Lock wait timeout exceeded"; and a 5xx, so the offline queue
		sends it again rather than dropping it as a refusal."""
		calls = []

		@retried
		def write():
			calls.append(1)
			raise frappe.QueryTimeoutError("1205")

		with patch.object(frappe.db, "rollback") as rolled_back:
			with self.assertRaises(OrderBusy) as raised:
				write()

		self.assertEqual(len(calls), 1, "fifty seconds waited already: not waited again")
		rolled_back.assert_called_once()
		self.assertIn("Try again", str(raised.exception))
		self.assertGreaterEqual(OrderBusy.http_status_code, 500)

	def test_any_other_failure_is_not_retried(self):
		calls = []

		@retried
		def write():
			calls.append(1)
			raise frappe.ValidationError("refused")

		with self.assertRaises(frappe.ValidationError):
			write()
		self.assertEqual(len(calls), 1)

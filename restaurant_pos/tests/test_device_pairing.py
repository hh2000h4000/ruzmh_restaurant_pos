# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""One terminal, one machine (`D-226`).

The till used to list every terminal the cashier could reach, so two machines
could take the same one — one drawer counted twice, receipts printing in the
wrong room. These tests hold the replacement: a code, a token, and a manager to
free it.
"""

import frappe

from restaurant_pos.api import session
from restaurant_pos.setup import test_fixtures
from restaurant_pos.tests.test_order import OrderTestBase
from restaurant_pos.utils import device, pairing


class DeviceTestBase(OrderTestBase):
	def _free_it(self) -> None:
		"""Leave the suite's till paired as the fixtures left it."""
		self.addCleanup(test_fixtures._pair_test_device, self.profile)

	def _code(self) -> str:
		self._free_it()
		return session.issue_device_code(self.profile)["code"]


class TestPairing(DeviceTestBase):
	def test_a_code_binds_this_machine_and_only_this_machine(self):
		token = session.pair_device(self._code(), device_name="Front till")["device_token"]

		self.assertTrue(session.load_pos_session(self.profile, device_token=token))
		with self.assertRaises(frappe.AuthenticationError):
			session.load_pos_session(self.profile, device_token="somebody else's")

	def test_the_machine_is_named_on_the_terminal(self):
		"""A manager has to be able to see which machine holds the till."""
		session.pair_device(self._code(), device_name="Front till")

		self.assertEqual(frappe.db.get_value("POS Profile", self.profile, "rpos_device_name"), "Front till")

	def test_a_code_works_once(self):
		code = self._code()
		session.pair_device(code)

		with self.assertRaises(frappe.AuthenticationError):
			session.pair_device(code)

	def test_an_expired_code_is_refused(self):
		code = self._code()
		frappe.db.set_value(
			"POS Profile", self.profile, "rpos_pairing_expires", "2020-01-01 00:00:00", update_modified=False
		)

		with self.assertRaises(frappe.AuthenticationError):
			session.pair_device(code)

	def test_a_wrong_code_is_refused(self):
		self._free_it()

		with self.assertRaises(frappe.AuthenticationError):
			session.pair_device("0000-0000")

	def test_the_code_is_never_stored_as_it_was_shown(self):
		"""A stolen database alone must not hand over a live code."""
		code = self._code()

		held = frappe.db.get_value("POS Profile", self.profile, "rpos_pairing_code_hash")
		self.assertNotIn(pairing.digits_of(code), held or "")
		self.assertEqual(held, pairing.digest(pairing.digits_of(code)))


class TestItIsAWrite(DeviceTestBase):
	"""**Frappe discards everything a GET writes.**

	The first pairing on a real till went out as a GET, because that is what our
	read helper sends. The server matched the code, wrote the token, answered
	with it — and the transaction was rolled back underneath the answer. The till
	held a token for a terminal that had never been paired, and the very next
	call said so. Nothing in the suite noticed: the tests call Python.
	"""

	def test_pairing_is_refused_over_a_get(self):
		for endpoint in (session.pair_device, session.issue_device_code, session.unpair_device):
			with self.subTest(endpoint=endpoint.__name__):
				self.assertEqual(
					frappe.allowed_http_methods_for_whitelisted_func.get(endpoint),
					["POST"],
					f"{endpoint.__name__} must be POST-only: a GET would roll its writes away",
				)


class TestFreeingIt(DeviceTestBase):
	def test_an_unpaired_terminal_refuses_every_machine(self):
		self._free_it()
		device.unpair(self.profile)

		with self.assertRaises(frappe.AuthenticationError):
			session.load_pos_session(self.profile, device_token=test_fixtures.DEVICE_TOKEN)

	def test_a_manager_frees_it_and_the_next_machine_takes_it(self):
		"""A till that broke at eight in the evening is replaced, not mourned."""
		first = session.pair_device(self._code(), device_name="Old till")["device_token"]
		session.unpair_device(self.profile)

		second = session.pair_device(self._code(), device_name="New till")["device_token"]

		self.assertTrue(session.load_pos_session(self.profile, device_token=second))
		with self.assertRaises(frappe.AuthenticationError):
			session.load_pos_session(self.profile, device_token=first)

	def test_both_ends_of_it_are_on_the_trail(self):
		"""Who took the till and who freed it (`FR-12.3`)."""
		session.pair_device(self._code(), device_name="Front till")
		session.unpair_device(self.profile)

		actions = frappe.get_all(
			"POS Audit Log",
			filters={
				"pos_profile": self.profile,
				"action_type": ("in", ["device_paired", "device_unpaired"]),
			},
			pluck="action_type",
		)
		self.assertIn("device_paired", actions)
		self.assertIn("device_unpaired", actions)

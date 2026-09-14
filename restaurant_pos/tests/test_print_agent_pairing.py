# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Pairing a print agent with a short code (`D-212`).

A technician at the restaurant's computer types eight digits instead of copying
a key and a secret between screens. The endpoint that takes the code has to be
open to a caller with no credentials — that is what the code is for — so what
these hold is everything that keeps that door narrow: once, briefly, only for
someone who may edit the agent, and slowly for anyone guessing.

Refs: D-204, D-212
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime
from frappe.utils.password import get_decrypted_password

from restaurant_pos.restaurant_pos.doctype.pos_print_agent import pos_print_agent as agents
from restaurant_pos.tests.test_permissions import _make_user
from restaurant_pos.tests.test_printing import _agent
from restaurant_pos.utils import manager_pin

#: Somewhere on the restaurant's network.
DEVICE = "203.0.113.30"
MANAGER = "rpos_pairing_manager@example.com"


class TestPairingAPrintAgent(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.agent = _agent("RPOS Pairing Agent")
		cls.manager = _make_user(MANAGER, "Restaurant Manager")
		frappe.db.commit()

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		frappe.db.set_value("POS Print Agent", self.agent, "is_active", 1)
		manager_pin.attempts_from(DEVICE, scope="pair").add_success_attempt()
		frappe.local.request_ip = DEVICE

	def tearDown(self):
		frappe.local.request_ip = None
		manager_pin.attempts_from(DEVICE, scope="pair").add_success_attempt()
		frappe.set_user("Administrator")
		super().tearDown()

	def _code(self) -> str:
		return agents.issue_pairing_code(self.agent)["code"]

	def _pair(self, code: str) -> dict:
		frappe.set_user("Guest")
		try:
			return agents.pair(code, host="till-pc")
		finally:
			frappe.set_user("Administrator")

	def test_a_code_hands_over_the_keys_the_agent_signs_in_with(self):
		answer = self._pair(self._code())

		user = frappe.db.get_value("POS Print Agent", self.agent, "user")
		self.assertEqual(answer["agent"], self.agent)
		self.assertEqual(answer["api_key"], frappe.db.get_value("User", user, "api_key"))
		self.assertEqual(answer["api_secret"], get_decrypted_password("User", user, "api_secret"))

	def test_a_code_works_once(self):
		code = self._code()
		self._pair(code)

		with self.assertRaises(frappe.AuthenticationError):
			self._pair(code)

	def test_an_expired_code_is_refused(self):
		code = self._code()
		frappe.db.set_value(
			"POS Print Agent", self.agent, "pairing_expires_at", add_to_date(now_datetime(), minutes=-1)
		)

		with self.assertRaises(frappe.AuthenticationError):
			self._pair(code)

	def test_asking_again_cancels_the_code_before(self):
		first = self._code()
		self._code()

		with self.assertRaises(frappe.AuthenticationError):
			self._pair(first)

	def test_the_hyphen_is_optional(self):
		self.assertEqual(self._pair(self._code().replace("-", ""))["agent"], self.agent)

	def test_the_code_is_not_kept_as_typed(self):
		digits = self._code().replace("-", "")

		stored = frappe.db.get_value("POS Print Agent", self.agent, "pairing_code_hash")
		self.assertNotIn(digits, stored)

	def test_an_agent_switched_off_cannot_be_paired(self):
		code = self._code()
		frappe.db.set_value("POS Print Agent", self.agent, "is_active", 0)

		with self.assertRaises(frappe.AuthenticationError):
			self._pair(code)

	def test_wrong_codes_make_the_device_wait_even_for_the_right_one(self):
		"""The door is open to anyone, so guessing has to be slow (`D-204`)."""
		code = self._code()
		for _ in range(manager_pin.WRONG_PINS_ALLOWED):
			with self.assertRaises(frappe.AuthenticationError):
				self._pair("0000-0000")

		with self.assertRaises(frappe.RateLimitExceededError):
			self._pair(code)

	def test_only_someone_who_may_edit_the_agent_can_issue_a_code(self):
		"""A Restaurant Manager reads agents but does not write them."""
		frappe.set_user(self.manager)

		with self.assertRaises(frappe.PermissionError):
			agents.issue_pairing_code(self.agent)

	def test_the_session_is_handed_back_to_guest(self):
		"""The rights are borrowed for the two writes the code authorises."""
		code = self._code()
		frappe.set_user("Guest")
		try:
			agents.pair(code, host="till-pc")
			self.assertEqual(frappe.session.user, "Guest")
		finally:
			frappe.set_user("Administrator")

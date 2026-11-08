# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The print agent installed from the till in one step (`D-424`, `docs/11` §4).

What the restaurant depends on: one request leaves the terminal printing
direct through an agent that pairs itself from its file's name; a computer
already printing is never taken from without being asked; another terminal's
agent is never taken at all; and only a manager may do it.
"""

from unittest.mock import patch

import frappe

from restaurant_pos.api import printing as api
from restaurant_pos.api import session as session_api
from restaurant_pos.restaurant_pos.doctype.pos_print_agent import pos_print_agent
from restaurant_pos.tests.test_order import _make_cashier
from restaurant_pos.tests.test_printing import PrintingTestBase, _agent
from restaurant_pos.utils import agent_install

ORIGIN = "https://pos.example.com"
PROGRAM = b"MZ the agent"


class TheAgentFromTheTill(PrintingTestBase):
	def setUp(self):
		super().setUp()
		program = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "RPOS-Print-Agent.exe",
				"is_private": 1,
				"content": PROGRAM,
			}
		).insert(ignore_permissions=True)
		frappe.db.set_single_value("Restaurant POS Settings", "print_agent_file", program.file_url)
		frappe.db.set_value(
			"POS Profile", self.profile, {"rpos_print_route": "server", "rpos_print_agent": None}
		)
		self.addCleanup(frappe.set_user, "Administrator")

	def _code(self, filename: str) -> str:
		return filename.removesuffix(".exe").rsplit("_", 1)[1]

	def test_one_request_leaves_the_till_printing_direct_through_an_agent_that_pairs_from_its_name(self):
		answer = agent_install.prepare(self.profile, ORIGIN)

		route, agent = frappe.db.get_value(
			"POS Profile", self.profile, ["rpos_print_route", "rpos_print_agent"]
		)
		self.assertEqual((route, agent), ("direct", answer["agent"]))
		self.assertTrue(answer["filename"].startswith("RPOS-Print-Agent_https_pos.example.com_443_"))

		paired = pos_print_agent.pair(self._code(answer["filename"]))
		self.assertEqual(paired["agent"], agent, "the code in the name pairs this agent")

	def test_the_ticket_hands_the_program_over_once_to_whoever_asked(self):
		ticket = agent_install.prepare(self.profile, ORIGIN)["ticket"]

		api.agent_file(ticket)
		self.assertEqual(frappe.local.response.filecontent, PROGRAM)
		self.assertEqual(frappe.local.response.type, "download")

		with self.assertRaises(frappe.PermissionError):
			api.agent_file(ticket)

	def test_the_terminal_s_agent_on_a_computer_is_moved_only_when_asked(self):
		mine = _agent("RPOS Test Till Agent")
		frappe.db.set_value("POS Print Agent", mine, "host_name", "POS1")
		frappe.db.set_value("POS Profile", self.profile, "rpos_print_agent", mine)

		self.assertEqual(agent_install.prepare(self.profile, ORIGIN), {"needs_move": "POS1"})
		self.assertFalse(frappe.db.get_value("POS Print Agent", mine, "pairing_code_hash"), "no code yet")

		self.assertEqual(agent_install.prepare(self.profile, ORIGIN, move=True)["agent"], mine)

	def test_another_terminal_s_agent_is_never_taken(self):
		"""Shared, it is the agent of a computer serving both: re-paired here, the other stops."""
		frappe.db.set_value("POS Print Agent", self.agent, "host_name", "POS1")
		frappe.db.set_value("POS Profile", self.profile, "rpos_print_agent", self.agent)

		# The test site has one terminal; the second is the question's answer.
		with patch.object(agent_install, "other_terminals_on", return_value=["كاشير 2"]):
			answer = agent_install.prepare(self.profile, ORIGIN, move=True)

		self.assertNotEqual(answer["agent"], self.agent)
		self.assertFalse(frappe.db.get_value("POS Print Agent", self.agent, "pairing_code_hash"))

	def test_a_bench_address_keeps_its_scheme_and_port(self):
		answer = agent_install.prepare(self.profile, "http://127.0.0.1:8000")
		self.assertTrue(answer["filename"].startswith("RPOS-Print-Agent_http_127.0.0.1_8000_"))

	def test_a_localhost_name_reaches_windows_as_127_0_0_1_and_its_page_still_prints(self):
		"""`D-425` — Chrome resolves `rpos.localhost`; Windows did not, and pairing failed."""
		answer = agent_install.prepare(self.profile, "http://rpos.localhost:8000")

		self.assertTrue(answer["filename"].startswith("RPOS-Print-Agent_http_127.0.0.1_8000_"))
		frappe.set_user(frappe.db.get_value("POS Print Agent", answer["agent"], "user"))
		self.assertIn("http://rpos.localhost:8000", api.claim(settings=1)["settings"]["origins"])

	def test_without_the_program_uploaded_it_says_so(self):
		frappe.db.set_single_value("Restaurant POS Settings", "print_agent_file", None)
		with self.assertRaises(frappe.ValidationError):
			agent_install.prepare(self.profile, ORIGIN)

	def test_the_till_asks_for_its_agent_s_key_again_from_this_machine_only(self):
		"""`D-425` — a till holding a key the agent dropped when it was paired again."""
		from restaurant_pos.utils import device

		agent = agent_install.prepare(self.profile, ORIGIN)["agent"]
		pos_print_agent.pair(self._code(agent_install.prepare(self.profile, ORIGIN, move=True)["filename"]))
		token = device.pair(device.issue_code(self.profile)["code"])["device_token"]

		printing = session_api.till_printing(self.profile, device_token=token)
		self.assertEqual(printing["token"], pos_print_agent.direct_token(agent, create=False))

		with self.assertRaises(frappe.AuthenticationError):
			session_api.till_printing(self.profile, device_token="another machine")

	def test_a_cashier_may_not(self):
		cashier = _make_cashier()
		frappe.set_user(cashier)
		frappe.local.rpos_permission_cache = {}

		with self.assertRaises(frappe.PermissionError):
			agent_install.prepare(self.profile, ORIGIN)
		self.assertEqual(frappe.db.get_value("POS Profile", self.profile, "rpos_print_route"), "server")

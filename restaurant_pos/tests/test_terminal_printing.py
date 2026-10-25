# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""A device prints its receipts on its own computer (`D-402`).

Refs: D-212, D-363, D-402
"""

import uuid

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant_pos.setup.test_fixtures import BRANCH, PROFILE
from restaurant_pos.tests.test_printing import _agent
from restaurant_pos.utils import terminal_printing


def _cable_printer(title: str, agent: str) -> str:
	existing = frappe.db.get_value("POS Printer", {"title": title, "branch": BRANCH})
	if existing:
		return existing
	return (
		frappe.get_doc(
			{
				"doctype": "POS Printer",
				"title": title,
				"branch": BRANCH,
				"print_agent": agent,
				"connection_type": "windows",
				"windows_printer_name": "Raport Bill",
				"printer_model": "generic",
				"paper_width": "80mm",
				"print_mode": "image",
				"is_active": 1,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


class AReceiptPrinterIsOnTheDevicesOwnComputer(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.mine = _agent("RPOS Till One Agent")
		self.theirs = _agent("RPOS Till Two Agent")
		self.my_printer = _cable_printer("RPOS Till One Receipts", self.mine)
		self.their_printer = _cable_printer("RPOS Till Two Receipts", self.theirs)
		self.profile = frappe.get_doc("POS Profile", PROFILE)
		self.addCleanup(
			frappe.db.set_value,
			"POS Profile",
			PROFILE,
			{
				"default_printer": self.profile.default_printer,
				"rpos_print_agent": self.profile.get("rpos_print_agent"),
			},
		)

	def test_another_tills_cable_printer_is_refused(self):
		"""Named alike on both computers, it would have printed at the other counter."""
		self.profile.rpos_print_agent = self.mine
		self.profile.default_printer = self.their_printer
		with self.assertRaises(frappe.ValidationError) as refused:
			self.profile.save(ignore_permissions=True)
		self.assertIn("RPOS Till Two Receipts", str(refused.exception))

	def test_its_own_cable_printer_is_taken(self):
		self.profile.rpos_print_agent = self.mine
		self.profile.default_printer = self.my_printer
		self.profile.save(ignore_permissions=True)
		self.assertEqual(self.profile.default_printer, self.my_printer)

	def test_a_cable_printer_asks_for_the_devices_agent_first(self):
		self.profile.rpos_print_agent = None
		self.profile.default_printer = self.my_printer
		with self.assertRaises(frappe.ValidationError):
			self.profile.save(ignore_permissions=True)

	def test_one_agent_may_serve_two_devices_on_purpose(self):
		"""A tablet beside the computer holding its printer: the device says so."""
		self.profile.rpos_print_agent = self.theirs
		self.profile.default_printer = self.their_printer
		self.profile.save(ignore_permissions=True)
		self.assertEqual(self.profile.rpos_print_agent, self.theirs)

	def test_a_network_printer_belongs_to_no_computer(self):
		network = frappe.db.get_value(
			"POS Printer", {"branch": BRANCH, "connection_type": "network", "is_active": 1}
		)
		if not network:
			self.skipTest("the test branch has no network printer")
		self.profile.rpos_print_agent = None
		self.profile.default_printer = network
		self.profile.save(ignore_permissions=True)

	def test_a_device_set_up_before_takes_its_printers_agent(self):
		"""The patch: what it prints through today is written down, so its next save is not refused."""
		from restaurant_pos.patches.v1_0 import terminal_print_agent_from_printer

		frappe.db.set_value(
			"POS Profile", PROFILE, {"default_printer": self.my_printer, "rpos_print_agent": None}
		)
		terminal_print_agent_from_printer.execute()
		self.assertEqual(frappe.db.get_value("POS Profile", PROFILE, "rpos_print_agent"), self.mine)


class SettingUpADevicesPrinting(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		vat = frappe.db.get_value("POS Profile", PROFILE, "taxes_and_charges")
		self.device = (
			frappe.get_doc(
				{
					"doctype": "POS Profile",
					"name": f"RPOS Setup Till {uuid.uuid4().hex[:6]}",
					"rpos_branch": BRANCH,
					"taxes_and_charges": vat,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_one_step_makes_the_agent_and_printer_and_joins_them(self):
		made = terminal_printing.prepare(self.device, "Raport Bill", "80mm")

		device = frappe.get_doc("POS Profile", self.device)
		self.assertEqual(device.rpos_print_agent, made["agent"])
		self.assertEqual(device.default_printer, made["printer"])
		printer = frappe.get_doc("POS Printer", made["printer"])
		self.assertEqual((printer.print_agent, printer.connection_type), (made["agent"], "windows"))
		self.assertEqual(printer.windows_printer_name, "Raport Bill")
		self.assertEqual(frappe.db.get_value("POS Print Agent", made["agent"], "branch"), BRANCH)

	def test_pressing_it_twice_makes_nothing_twice(self):
		first = terminal_printing.prepare(self.device, "Raport Bill")
		second = terminal_printing.prepare(self.device, "Raport Bill")
		self.assertEqual(first, second)

	def test_a_cashier_cannot_set_it_up(self):
		from restaurant_pos.api import printing as api
		from restaurant_pos.tests.test_permissions import CASHIER, _make_user

		frappe.set_user(_make_user(CASHIER, "POS Cashier"))
		try:
			with self.assertRaises(frappe.PermissionError):
				api.prepare_terminal_printing(self.device, "Raport Bill")
		finally:
			frappe.set_user("Administrator")

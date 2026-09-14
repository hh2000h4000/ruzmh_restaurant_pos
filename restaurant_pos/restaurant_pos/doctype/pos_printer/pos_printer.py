# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import ipaddress
import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class POSPrinter(Document):
	def validate(self):
		self.validate_connection()
		self.validate_fallback_printer()
		self.validate_agent_branch()

	def validate_connection(self):
		"""Each connection type keeps its own address and clears the others'.

		`windows` (`D-212`) was added beside `network` and `usb` and fell into
		the USB branch, so a printer installed in Windows could not be saved
		without a vendor id it does not have — found by the user saving the
		first one.
		"""
		if self.connection_type != "network":
			self.ip_address = None
		if self.connection_type != "usb":
			self.usb_vendor_id = None
			self.usb_product_id = None
		if self.connection_type != "windows":
			self.windows_printer_name = None

		if self.connection_type == "network":
			self.validate_ip_address()
			self.validate_port()
		elif self.connection_type == "windows":
			self.windows_printer_name = (self.windows_printer_name or "").strip()
			if not self.windows_printer_name:
				frappe.throw(_("Windows Printer Name is required for a printer installed in Windows."))
		else:
			self.validate_usb_ids()

	def validate_ip_address(self):
		if not self.ip_address:
			frappe.throw(_("IP Address is required for a network printer."))
		try:
			ipaddress.ip_address(self.ip_address.strip())
		except ValueError:
			frappe.throw(_("'{0}' is not a valid IP address.").format(self.ip_address))
		self.ip_address = self.ip_address.strip()

	def validate_port(self):
		if not self.port:
			self.port = 9100
		if not 1 <= cint(self.port) <= 65535:
			frappe.throw(_("Port must be between 1 and 65535."))

	def validate_usb_ids(self):
		for fieldname in ("usb_vendor_id", "usb_product_id"):
			value = (self.get(fieldname) or "").strip().lower().removeprefix("0x")
			if not value:
				frappe.throw(
					_("{0} is required for a USB printer.").format(_(self.meta.get_label(fieldname)))
				)
			if not re.fullmatch(r"[0-9a-f]{4}", value):
				frappe.throw(
					_("{0} must be a 4-digit hex value, for example 04b8.").format(
						_(self.meta.get_label(fieldname))
					)
				)
			self.set(fieldname, value)

	def validate_fallback_printer(self):
		if self.fallback_printer and self.fallback_printer == self.name:
			frappe.throw(_("A printer cannot be its own fallback printer."))

	def validate_agent_branch(self):
		"""An agent only reaches printers on its own network (D-084).

		Caught here because the alternative is a job that queues cleanly, waits
		for an agent in another city, and is only noticed when a customer asks
		where their receipt is.
		"""
		if not self.print_agent:
			return

		agent_branch = frappe.db.get_value("POS Print Agent", self.print_agent, "branch")
		if agent_branch != self.branch:
			frappe.throw(
				_("{0} runs at {1} and cannot reach a printer at {2}.").format(
					self.print_agent, agent_branch, self.branch
				)
			)

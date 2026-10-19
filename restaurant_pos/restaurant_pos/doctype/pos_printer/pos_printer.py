# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import ipaddress
import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

#: Narrower than any 58mm head and wider than a 104mm one: outside this, the
#: number is a typo rather than a printer.
MIN_PRINT_DOTS = 200
MAX_PRINT_DOTS = 832


class POSPrinter(Document):
	def validate(self):
		self.validate_connection()
		self.validate_print_width()
		self.validate_fallback_printer()
		self.validate_agent_branch()
		self.validate_unique_in_branch()

	def validate_print_width(self):
		"""A typo here draws every receipt ten times too wide, or a sliver (`D-215`)."""
		width = cint(self.print_width_dots)
		if width and not MIN_PRINT_DOTS <= width <= MAX_PRINT_DOTS:
			frappe.throw(
				_("Print Width must be between {0} and {1} dots.").format(MIN_PRINT_DOTS, MAX_PRINT_DOTS)
			)

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
		# D-363 — a failed ticket is reprinted in the same building.
		from restaurant_pos.utils.printer_branch import assert_in_branch

		assert_in_branch(self.fallback_printer, self.branch, used_by=self.title)

	def validate_unique_in_branch(self):
		"""One «المشاوي» per branch (`D-363`).

		Two branches may each have a grill printer — and may even share an IP,
		each being its own network — but inside one branch two printers with one
		name are a coin toss for whoever sets up the stations.
		"""
		same = {"branch": self.branch, "name": ("!=", self.name or ""), "title": self.title}
		if frappe.db.exists("POS Printer", same):
			frappe.throw(_("{0} already has a printer called {1}.").format(self.branch, self.title))

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

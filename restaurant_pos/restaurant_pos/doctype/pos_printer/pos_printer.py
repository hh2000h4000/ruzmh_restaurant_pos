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

	def validate_connection(self):
		if self.connection_type == "network":
			self.usb_vendor_id = None
			self.usb_product_id = None
			self.validate_ip_address()
			self.validate_port()
		else:
			self.ip_address = None
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

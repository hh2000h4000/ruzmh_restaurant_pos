# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt
from frappe.utils.password import update_password


class POSPermissionSet(Document):
	def validate(self):
		self.validate_discount_limits()
		self.hold_pin_aside()

	def on_update(self):
		self.store_pin_hashed()

	def validate_discount_limits(self):
		for fieldname in ("max_item_discount_pct", "max_order_discount_pct"):
			value = flt(self.get(fieldname))
			if not 0 <= value <= 100:
				frappe.throw(_("{0} must be between 0 and 100.").format(_(self.meta.get_label(fieldname))))

	def hold_pin_aside(self):
		"""Keep the PIN out of Frappe's own Password-field storage.

		A ``Password`` DocField is persisted by ``set_encrypted_password()`` with
		``encrypted = 1`` — reversible, so anyone with the site's encryption key
		can read the PIN back. ``check_password()`` also ignores those rows; it
		only reads ``encrypted = 0``. Storing it that way would be both readable
		and unverifiable.

		So the value is taken off the document before save and written as a
		one-way hash in :meth:`store_pin_hashed`.
		"""
		pin = (self.manager_pin or "").strip()
		self.manager_pin = None

		if not pin:
			self._new_manager_pin = None
			return

		if not pin.isdigit() or len(pin) != 4:
			frappe.throw(_("The manager PIN must be exactly 4 digits."))

		self._new_manager_pin = pin

	def store_pin_hashed(self):
		pin = getattr(self, "_new_manager_pin", None)
		if not pin:
			return

		update_password(self.name, pin, doctype=self.doctype, fieldname="manager_pin")
		self._new_manager_pin = None

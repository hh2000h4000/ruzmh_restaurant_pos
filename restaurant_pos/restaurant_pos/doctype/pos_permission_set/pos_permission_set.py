# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from restaurant_pos.utils import permissions as perms
from restaurant_pos.utils.audit import log_permission_change


class POSPermissionSet(Document):
	"""Action-level rights for one role.

	The manager PIN is deliberately not here: it belongs to a person, not a role
	(``utils/manager_pin.py``, ``DECISIONS.md`` D-016).

	**The escalation guard lives here, on the record itself** (`D-201`, `FR-12.6`).
	It used to sit in one API endpoint, and `D-197` sends every manager to the
	desk form instead — which went through no guard at all and left nothing in
	the audit log. A rule that has to be remembered at each door is a rule that
	will be missing from one of them (`CLAUDE.md` §5.5).
	"""

	def validate(self):
		self.validate_discount_limits()
		self._changes = self._guard()

	def validate_discount_limits(self):
		for fieldname in ("max_item_discount_pct", "max_order_discount_pct"):
			value = flt(self.get(fieldname))
			if not 0 <= value <= 100:
				frappe.throw(_("{0} must be between 0 and 100.").format(_(self.meta.get_label(fieldname))))

	def _guard(self) -> dict:
		"""Refuse an edit that hands out more than the editor holds, and say what changed.

		Superusers pass: a System Manager configuring the system is the one who
		writes the shipped defaults, and there is nobody above them to ask.
		"""
		if perms.is_superuser():
			return {}

		return perms.assert_may_edit_permission_set(self.role, self.as_dict())

	def on_update(self):
		if self._changes:
			log_permission_change(target=self.role, changes=self._changes)
			self._changes = {}

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Carry `can_set_up_devices` (`D-424`) to the shipped sets on sites installed before it.

The same gap `grant_missing_permission_defaults` closes, for one more right: the
column is born holding `0` on every existing row, so the managers it was written
for could not install the print agent from the till. Safe to write for the same
reason — the column is new, so a `0` there is nobody's decision. Only the five
shipped sets; idempotent.
"""

import frappe

from restaurant_pos.setup.defaults import PERMISSION_SETS

FIELD = "can_set_up_devices"


def execute():
	for role, values in PERMISSION_SETS.items():
		if not frappe.db.exists("POS Permission Set", role):
			continue
		wanted = values.get(FIELD, 0)
		if frappe.db.get_value("POS Permission Set", role, FIELD) != wanted:
			frappe.db.set_value("POS Permission Set", role, FIELD, wanted, update_modified=False)

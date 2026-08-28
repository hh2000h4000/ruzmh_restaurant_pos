# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Give the shipped permission sets the new ``can_change_order_type`` right.

``setup/defaults.py`` skips a ``POS Permission Set`` that already exists, so a
site installed before this field gained it would leave every role at ``0`` and
the feature invisible — including to the manager it was written for.

Only the five sets ``setup/defaults.py`` ships are touched, and each is set to
what those defaults say. Overwriting a ``0`` is safe here precisely because the
field is new: every existing row holds ``0`` because the column was just added,
not because anybody chose it. A set the restaurant created itself is left alone.

Idempotent: a row already holding the shipped value is skipped.
"""

import frappe

from restaurant_pos.setup.defaults import PERMISSION_SETS

FIELD = "can_change_order_type"


def execute():
	for role, values in PERMISSION_SETS.items():
		if not frappe.db.exists("POS Permission Set", role):
			continue

		wanted = values.get(FIELD, 0)
		if frappe.db.get_value("POS Permission Set", role, FIELD) == wanted:
			continue

		frappe.db.set_value("POS Permission Set", role, FIELD, wanted, update_modified=False)

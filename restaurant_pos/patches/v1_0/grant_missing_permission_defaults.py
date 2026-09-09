# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Give the shipped permission sets two rights that never reached an old site.

**Nothing was deleted and nothing was overwritten.** `setup/defaults.py` runs at
install and skips a `POS Permission Set` that already exists — which is right,
because re-applying it on every migrate would put back the ceiling a manager
lowered on purpose. The cost is the other direction: when a later version adds a
right, `bench migrate` adds the *column*, every existing row is born holding `0`
because a new column needs a value, and the shipped `1` never lands. The
permission is then off for the manager it was written for, with nothing anywhere
saying why (`D-074`).

`grant_change_order_type` fixed exactly this once. It happened twice more and was
not noticed either time:

* ``can_split_bill`` — off for the senior cashier and both manager sets;
* ``can_close_day_with_open_orders`` — off for **every** role including the
  managers, so on a branch that requires bills to be settled before the day ends
  (`D-105`, `D-156`) nobody at all could close it. The user hit that wall.

Both are safe to write because the field is new: a row holds `0` because the
column was just added, not because anybody chose it. Fields that predate this —
the discount ceilings above all — are deliberately **not** touched, because
there a `0` may well be somebody's decision.

Only the five sets `setup/defaults.py` ships. A permission set the restaurant
created itself is left alone. Idempotent: a row already holding the shipped value
is skipped.

Refs: D-013, D-105, D-156, D-167
"""

import frappe

from restaurant_pos.setup.defaults import PERMISSION_SETS

#: Named one by one rather than syncing every field, because the argument that
#: makes this safe — the column was born empty — is true of these two and false
#: of the rest.
FIELDS = ("can_split_bill", "can_close_day_with_open_orders")


def execute():
	for role, values in PERMISSION_SETS.items():
		if not frappe.db.exists("POS Permission Set", role):
			continue

		for field in FIELDS:
			wanted = values.get(field, 0)
			if frappe.db.get_value("POS Permission Set", role, field) == wanted:
				continue

			frappe.db.set_value("POS Permission Set", role, field, wanted, update_modified=False)

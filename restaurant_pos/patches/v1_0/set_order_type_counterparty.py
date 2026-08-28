# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Mark which order types are owed by a third party (``D-038``).

``counterparty`` decides whether an order may be turned into another type: only
two ``walk_in`` types can be swapped, because only there do the parties to the
sale stay the same. The field defaults to ``walk_in``, which is right for a
restaurant's own dine-in, takeaway and delivery — and wrong for the delivery
apps and corporate accounts shipped in ``setup/defaults.py``, where a platform
or a company holds the debt.

Matched on the shipped titles only. A restaurant that renamed one, or added its
own platform, sets the field itself; guessing from a payment method would
mislabel a cash-on-delivery type that merely looks similar.

Idempotent: a type already marked ``account`` is skipped.
"""

import frappe

#: The titles ``setup/defaults.py`` creates for third-party types.
ACCOUNT_TYPES = ("HungerStation", "Jahez", "Talabat", "Corporate")


def execute():
	for title in ACCOUNT_TYPES:
		name = frappe.db.get_value("Restaurant Order Type", {"title": title}, "name")
		if not name:
			continue

		if frappe.db.get_value("Restaurant Order Type", name, "counterparty") == "account":
			continue

		frappe.db.set_value(
			"Restaurant Order Type", name, "counterparty", "account", update_modified=False
		)

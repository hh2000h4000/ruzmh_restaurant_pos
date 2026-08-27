# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Replace the emoji shipped as order-type icons with icon names.

The cashier screen draws a real icon when the ``icon`` field holds a known name
and renders anything else as written. The defaults originally shipped emoji,
which every platform draws differently, none of which sit on a text baseline —
a large part of why the screen looked dated.

Only rows that still hold exactly the emoji we shipped are touched. A
restaurant that deliberately picked its own icon keeps it.

Idempotent: a row already holding a name does not match and is skipped.
"""

import frappe

#: The emoji each shipped order type used to carry, by title.
REPLACEMENTS = {
	"Dine In": ("\U0001f3e0", "home"),
	"Takeaway": ("\U0001f961", "bag"),
	"Delivery": ("\U0001f6f5", "truck"),
	"HungerStation": ("\U0001f6f5", "mobile"),
	"Jahez": ("\U0001f4f1", "mobile"),
	"Talabat": ("\U0001f4f1", "mobile"),
	"Corporate": ("\U0001f3e2", "users"),
}


def execute():
	for title, (was, now) in REPLACEMENTS.items():
		name = frappe.db.get_value("Restaurant Order Type", {"title": title}, "name")
		if not name:
			continue

		if frappe.db.get_value("Restaurant Order Type", name, "icon") != was:
			continue

		frappe.db.set_value("Restaurant Order Type", name, "icon", now, update_modified=False)

	frappe.clear_cache(doctype="Restaurant Order Type")

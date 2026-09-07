# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Clearing what the suite leaves behind.

Not a test. A suite that grows its own site gets slower every time it runs, and
a check that costs twenty minutes is a check that gets skipped — so keeping the
site small is part of keeping the gate worth running.

Refs: `D-155`
"""

import frappe

from restaurant_pos.api.order import OPEN_STATUSES

#: A bill that never became a sale. Nothing in the accounts points at it, so it
#: can go; a bill that has an invoice stays, or the invoice would be left
#: pointing at nothing.
UNSOLD = {"sales_invoice": ("in", ("", None))}

#: What hangs off an order, and the column it hangs by. Cleared first, so
#: nothing is orphaned if the run stops halfway.
DEPENDENTS = (
	("Restaurant Order Item", "parent"),
	("Kitchen Order Ticket", "restaurant_order"),
	("POS Order Activity", "restaurant_order"),
	("POS Audit Log", "restaurant_order"),
)

#: How many ids go into one `IN (…)`. A list of fifteen thousand is one query
#: the database plans badly and one failure that undoes the whole run.
BATCH = 500


def clear_test_residue(confirm_site: str | None = None) -> None:
	"""Delete every unsold order on this site, and everything hanging off it.

	The site has to be named again in ``confirm_site``. **`allow_tests` is not a
	guard** — it is set on the demo site too, so a check against it would have
	let this delete a real cashier's open bills while reporting success. Naming
	the site is the one thing an operator cannot do by accident.
	"""
	site = frappe.local.site

	if confirm_site != site:
		frappe.throw(
			f"Refusing to clear {site}: pass confirm_site='{site}' if that is really the site you mean. "
			"Nothing was deleted."
		)

	names = frappe.get_all("Restaurant Order", filters=UNSOLD, pluck="name")
	if not names:
		print(f"{site}: nothing to clear")
		return

	print(f"{site}: clearing {len(names)} unsold orders")

	# A table still pointing at a bill that is about to go would stay occupied
	# for ever, and nobody could be seated on it again (`BR-066`).
	frappe.db.set_value(
		"Restaurant Table",
		{"current_order": ("in", names)},
		{"current_order": None, "status": "available"},
	)

	for start in range(0, len(names), BATCH):
		batch = names[start : start + BATCH]

		for doctype, column in DEPENDENTS:
			frappe.db.delete(doctype, {column: ("in", batch)})

		frappe.db.delete("Restaurant Order", {"name": ("in", batch)})
		frappe.db.commit()

	left = frappe.db.count("Restaurant Order", {"status": ("in", OPEN_STATUSES)})
	print(f"{site}: bills left on the floor: {left}")

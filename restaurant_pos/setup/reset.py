# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Putting a site back to day one, without touching what it was set up as.

Two callers, one job (`CLAUDE.md` §5.5): the suite leaves unsold bills behind on
the test site, and a restaurant being handed over wants its trial sales gone. The
second is the first without the filter, so it is one function with one guard
rather than two that drift.

**What this never touches:** the menu, the tables, the sections, the printers,
the order types, the permission sets, the screen layouts, the ZATCA settings —
everything a person configured. Only what the till *did* is removed.

**And it stops at our own doorstep.** `Sales Invoice`, `GL Entry`, `POS Opening
Entry` and the rest are ERPNext's, submitted and posted to the accounts, and
deleting them from underneath is not a thing an app may do to a ledger. ERPNext
ships `Transaction Deletion Record` for exactly that, and it is the tool to use —
it cancels, deletes and resets the company's naming series in the right order.

Refs: `D-155`, `D-159`
"""

import frappe

#: A bill that never became a sale. Nothing in the accounts points at it, so it
#: can go on its own; a bill with an invoice waits for the ledger to be cleared
#: first, or the invoice is left pointing at nothing.
UNSOLD = {"sales_invoice": ("in", ("", None))}

#: What hangs off an order, and the column it hangs by. Cleared first, so
#: nothing is orphaned if the run stops halfway.
ORDER_DEPENDENTS = (
	("Restaurant Order Item", "parent"),
	("Kitchen Order Ticket", "restaurant_order"),
	("POS Order Activity", "restaurant_order"),
	("POS Audit Log", "restaurant_order"),
)

#: Records of what the till did, belonging to no order in particular. Emptied
#: outright on a full reset — a print job for a bill that no longer exists is
#: not history, it is litter.
STANDALONE = (
	"POS Print Job",
	"POS Sync Entry",
	"Restaurant Shift",
	# **The short number the customer is told** (`FR-2.10`). Left behind, the
	# first bill of a fresh restaurant is #175 — which is the one number on the
	# receipt anybody would notice.
	"POS Order Counter",
)

#: How many ids go into one `IN (…)`. A list of fifteen thousand is one query the
#: database plans badly and one failure that undoes the whole run.
BATCH = 500


def clear_pos_transactions(confirm_site: str | None = None, unsold_only: int | bool = False) -> None:
	"""Delete what the till did on this site. Keeps everything it was set up as.

	The site has to be named again in ``confirm_site``. **`allow_tests` is not a
	guard** — it is true on the demo site too, so a check against it would have
	let this delete a real cashier's open bills while reporting success. Naming
	the site is the one thing an operator cannot do by accident.

	``unsold_only`` keeps every bill that became an invoice, which is what the
	test site needs: there the accounts are nobody's concern and the residue is
	the abandoned drafts.
	"""
	site = frappe.local.site

	if confirm_site != site:
		frappe.throw(
			f"Refusing to clear {site}: pass confirm_site='{site}' if that is really the site "
			"you mean. Nothing was deleted."
		)

	unsold_only = bool(int(unsold_only or 0))
	names = frappe.get_all("Restaurant Order", filters=UNSOLD if unsold_only else {}, pluck="name")

	print(f"{site}: clearing {len(names)} orders" + (" (unsold only)" if unsold_only else ""))

	if names:
		# A table still pointing at a bill that is about to go would stay
		# occupied for ever, and nobody could be seated on it again (`BR-066`).
		frappe.db.set_value(
			"Restaurant Table",
			{"current_order": ("in", names)},
			{"current_order": None, "status": "available"},
		)

		for start in range(0, len(names), BATCH):
			batch = names[start : start + BATCH]

			for doctype, column in ORDER_DEPENDENTS:
				frappe.db.delete(doctype, {column: ("in", batch)})

			frappe.db.delete("Restaurant Order", {"name": ("in", batch)})
			frappe.db.commit()

	if not unsold_only:
		for doctype in STANDALONE:
			frappe.db.delete(doctype)
			print(f"{site}: emptied {doctype}")

		# The terminals pointed at a day that no longer exists would refuse to
		# sell and explain nothing (`BR-044`). Opening a shift sets this again.
		frappe.db.set_value("POS Profile", {"restaurant_shift": ("is", "set")}, "restaurant_shift", None)
		frappe.db.set_value(
			"Restaurant Table",
			{"status": ("!=", "available")},
			{"status": "available", "current_order": None},
		)
		frappe.db.commit()

	print(f"{site}: orders left: {frappe.db.count('Restaurant Order')}")
	print(f"{site}: invoices are ERPNext's — use Transaction Deletion Record for those")

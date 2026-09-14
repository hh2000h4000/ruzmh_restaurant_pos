# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""ERPNext's "Delete Transactions" clears the till with the books (`D-210`).

A restaurant tries the system for a week, then wants to start for real. ERPNext
has one button for that — Company → Delete Transactions — and it deletes what
carries a `company` link. RPOS documents carry a branch instead, so the button
used to empty the books and leave the till standing: 187 closed bills pointing
at invoices that no longer existed, and a day report reading zero beside them
(`D-061`).

**One button, not two.** A second one in the POS settings would ask the
question ERPNext already asks (`CLAUDE.md` §5.5), and an owner who pressed one
and forgot the other would get exactly the half-deleted system above. So this
runs when ERPNext's own record is submitted, **inside the same transaction**:
the till's documents for that company's branches go with it, or the submit
fails and nothing goes.

Hooked in `hooks.py`, so every site that installs the app has it and nothing in
ERPNext is edited. ERPNext restricts the record to System Manager, and so this.

**Nothing here can be excluded.** ERPNext only lets its exclusion table lose
rows, never gain them, so these doctypes cannot be put on it.

Refs: D-061, D-210
"""

import operator
from functools import reduce

import frappe

from restaurant_pos.utils.order import release_table

#: The ERPNext documents a replay may point at, deleted by the same button — so
#: their replay records go too. Customers and addresses are not on ERPNext's
#: list, so replays that made one are kept with it.
ERPNEXT_REPLAYED = ("Sales Invoice", "POS Opening Entry", "POS Closing Entry")

#: Floor states a trial leaves behind. `inactive` is not one: a table taken out
#: of service is setup, and stays out.
LEFT_BY_SERVICE = ("occupied", "cleaning", "reserved")


def on_submit(doc, method=None):
	"""`Transaction Deletion Record.on_submit`."""
	delete_pos_transactions(doc.company)


def delete_pos_transactions(company: str) -> dict[str, int]:
	"""Delete every till document of ``company``'s branches; return what went.

	Setup is never touched: order types, tables, printers, permission sets,
	promotions, themes, settings. Only what service produced — and the floor and
	terminals are handed back as they were before the first order.
	"""
	branches = frappe.get_all("Branch", filters={"company": company}, pluck="name")
	if not branches:
		return {}

	in_branches = {"branch": ("in", branches)}

	# **Subqueries, not lists of names.** Measured on the test site: `get_all`
	# with 10,500 order names in an `in` filter took 32 s to find 137 kitchen
	# tickets — the filter is prepared a value at a time — while deleting those
	# same 10,500 orders took under a second. A deletion that runs inside the
	# submit request cannot spend a minute preparing a filter.
	order = frappe.qb.DocType("Restaurant Order")
	ticket = frappe.qb.DocType("Kitchen Order Ticket")
	shift = frappe.qb.DocType("Restaurant Shift")
	sync_entry = frappe.qb.DocType("POS Sync Entry")

	orders_of = frappe.qb.from_(order).select(order.name).where(order.branch.isin(branches))
	tickets_of = frappe.qb.from_(ticket).select(ticket.name).where(ticket.restaurant_order.isin(orders_of))
	shifts_of = frappe.qb.from_(shift).select(shift.name).where(shift.branch.isin(branches))

	orders = orders_of.run(pluck=True)
	kots = tickets_of.run(pluck=True)
	shifts = shifts_of.run(pluck=True)

	# Found before anything is deleted: a replay record names its document, and
	# once the document is gone there is nothing left to match it by.
	replayed = {
		"Restaurant Order": orders_of,
		"Kitchen Order Ticket": tickets_of,
		"Restaurant Shift": shifts_of,
	}
	for doctype in ERPNEXT_REPLAYED:
		source = frappe.qb.DocType(doctype)
		replayed[doctype] = frappe.qb.from_(source).select(source.name).where(source.company == company)
	sync = (
		frappe.qb.from_(sync_entry)
		.select(sync_entry.name)
		.where(
			reduce(
				operator.or_,
				[
					(sync_entry.reference_doctype == doctype) & sync_entry.reference_name.isin(query)
					for doctype, query in replayed.items()
				],
			)
		)
		.run(pluck=True)
	)

	gone: dict[str, int] = {}
	for doctype, names in (
		("POS Order Activity", frappe.get_all("POS Order Activity", filters=in_branches, pluck="name")),
		("POS Audit Log", frappe.get_all("POS Audit Log", filters=in_branches, pluck="name")),
		("POS Print Job", frappe.get_all("POS Print Job", filters=in_branches, pluck="name")),
		("POS Sync Entry", sync),
		("Kitchen Order Ticket", kots),
		(
			"Restaurant Reservation",
			frappe.get_all("Restaurant Reservation", filters=in_branches, pluck="name"),
		),
		("Restaurant Order", orders),
		("Restaurant Shift", shifts),
		# The numbering memory: without it the first real bill carries on from
		# the trial's last number.
		("POS Order Counter", frappe.get_all("POS Order Counter", filters=in_branches, pluck="name")),
	):
		_delete(doctype, names, gone)

	_hand_the_floor_back(branches)

	for profile in frappe.get_all(
		"POS Profile", filters={"company": company, "restaurant_shift": ("is", "set")}, pluck="name"
	):
		frappe.db.set_value("POS Profile", profile, "restaurant_shift", None, update_modified=False)

	return gone


def _delete(doctype: str, names: list[str], gone: dict[str, int]) -> None:
	"""A document with its child rows, history and comments — what ERPNext's own
	deletion removes alongside each document it deletes."""
	if not names:
		return

	for field in frappe.get_meta(doctype).get_table_fields():
		frappe.db.delete(field.options, {"parenttype": doctype, "parent": ("in", names)})
	frappe.db.delete("Version", {"ref_doctype": doctype, "docname": ("in", names)})
	frappe.db.delete("Comment", {"reference_doctype": doctype, "reference_name": ("in", names)})
	frappe.db.delete(doctype, {"name": ("in", names)})
	gone[doctype] = len(names)


def _hand_the_floor_back(branches: list[str]) -> None:
	"""Free the tables the trial left held, through the one function that frees
	a table (`BR-066`) — it asks what is still open, and now nothing is."""
	sections = frappe.get_all("Restaurant Section", filters={"branch": ("in", branches)}, pluck="name")
	if not sections:
		return

	held = frappe.get_all(
		"Restaurant Table",
		filters={"section": ("in", sections)},
		or_filters={"status": ("in", LEFT_BY_SERVICE), "current_order": ("is", "set")},
		pluck="name",
	)
	for table in held:
		release_table(table)

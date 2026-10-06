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
from frappe.model.naming import NamingSeries
from frappe.query_builder.functions import Count, Max
from frappe.utils import cint

from restaurant_pos.utils import invoice_number
from restaurant_pos.utils.order import release_table

#: The ERPNext documents a replay may point at, deleted by the same button — so
#: their replay records go too. Customers and addresses are not on ERPNext's
#: list, so replays that made one are kept with it.
ERPNEXT_REPLAYED = ("Sales Invoice", "POS Opening Entry", "POS Closing Entry")

#: Floor states a trial leaves behind. `inactive` is not one: a table taken out
#: of service is setup, and stays out.
LEFT_BY_SERVICE = ("occupied", "cleaning", "reserved")

#: The till's documents named from a `naming_series` field. ERPNext's button
#: restarts a counter only when the pattern is the doctype's own `autoname`, so it
#: skips these — which is how `RO-2026-09-00067` followed a deletion that left no
#: orders at all (the user's first try of `D-210`).
#:
#: Tickets, activity rows and print jobs are not here: nobody reads their names,
#: so they have none to count (`D-310`). And a terminal's own order and invoice
#: counters are restarted by `invoice_number.restart_counters`.
NUMBERED = (
	"Restaurant Order",
	"Restaurant Shift",
	"Restaurant Reservation",
)


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

	cards = _gift_cards_of(company, branches)
	_give_back_coupon_uses(orders_of)

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
		# `D-268` — money documents of our own, each carrying an entry ERPNext is
		# about to delete. Left behind, a card kept its balance with no liability
		# under it, and a drawer movement named a journal entry that was gone.
		("POS Cash Movement", frappe.get_all("POS Cash Movement", filters=in_branches, pluck="name")),
		("POS Gift Card Entry", _gift_card_entries(cards)),
		("POS Gift Card", cards),
	):
		_delete(doctype, names, gone)

	_restart_numbering()
	_hand_the_floor_back(branches)

	for profile in frappe.get_all(
		"POS Profile", filters={"company": company, "restaurant_shift": ("is", "set")}, pluck="name"
	):
		frappe.db.set_value("POS Profile", profile, "restaurant_shift", None, update_modified=False)

	return gone


def _give_back_coupon_uses(orders_of) -> None:
	"""Take back the uses the deleted orders counted on their coupons (`D-268`).

	**The code is setup; its count is service.** A coupon may be printed and in a
	guest's pocket, so it stays — but a single-use code tried once in the trial
	would otherwise read *used* forever. Only what these orders counted is taken
	back, so another company's uses of a shared code stand.
	"""
	order = frappe.qb.DocType("Restaurant Order")
	spent = (
		frappe.qb.from_(order)
		.select(order.coupon, Count("*"))
		.where(order.name.isin(orders_of) & (order.coupon_spent == 1) & order.coupon.isnotnull())
		.groupby(order.coupon)
		.run()
	)
	for coupon, uses in spent:
		used = cint(frappe.db.get_value("POS Coupon", coupon, "used"))
		frappe.db.set_value("POS Coupon", coupon, "used", max(used - cint(uses), 0), update_modified=False)


def _gift_cards_of(company: str, branches: list[str]) -> list[str]:
	"""Every card this company's trial made (`D-268`).

	**Found through the books, not only the branch.** A card issued from the
	office has no branch and no terminal: what ties it to the company is the
	journal entry or invoice on its rows. ERPNext only queues its own deletion on
	submit (`TransactionDeletionRecord.on_submit`), so those are still here.
	"""
	entry = frappe.qb.DocType("POS Gift Card Entry")
	journal = frappe.qb.DocType("Journal Entry")
	invoice = frappe.qb.DocType("Sales Invoice")
	journals = frappe.qb.from_(journal).select(journal.name).where(journal.company == company)
	invoices = frappe.qb.from_(invoice).select(invoice.name).where(invoice.company == company)

	through_rows = (
		frappe.qb.from_(entry)
		.select(entry.gift_card)
		.where(
			entry.branch.isin(branches)
			| entry.journal_entry.isin(journals)
			| entry.sales_invoice.isin(invoices)
		)
		.distinct()
		.run(pluck=True)
	)
	issued_here = frappe.get_all("POS Gift Card", filters={"issued_branch": ("in", branches)}, pluck="name")
	return sorted(set(through_rows) | set(issued_here))


def _gift_card_entries(cards: list[str]) -> list[str]:
	if not cards:
		return []
	return frappe.get_all("POS Gift Card Entry", filters={"gift_card": ("in", cards)}, pluck="name")


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


def _restart_numbering() -> None:
	"""Put each series back at the highest number still standing — zero if none.

	**Never simply zero.** The counter is shared by the whole site, and another
	company's orders may still carry numbers from it; setting it below them
	hands the next bill a name that already exists. Only the current period's
	prefix is restarted: that is the one the next document is named from.
	"""
	for doctype in NUMBERED:
		options = frappe.get_meta(doctype).get_field("naming_series").options or ""
		for option in filter(None, (line.strip() for line in options.split("\n"))):
			series = NamingSeries(option)
			prefix = series.get_prefix()
			table = frappe.qb.DocType(doctype)
			last = (
				frappe.qb.from_(table)
				.select(Max(table.name))
				.where(table.name.like(f"{prefix}%"))
				.run()[0][0]
			)
			series.update_counter(cint(last[len(prefix) :]) if last else 0)

	# And every terminal's own invoice counter (`D-309`): ERPNext restarts the
	# series it knows from the form, and these are not on the form.
	invoice_number.restart_counters()

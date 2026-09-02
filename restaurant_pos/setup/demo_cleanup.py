# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Remove the smoke-test residue the demo site accumulated.

Early testing left documents named `RPOS-TEST-*` and `RPOS-PLAN-*` in the demo
data — items, tables, production centers, a hall — and they show up wherever the
demo does. A kitchen ticket printed `RPOS-PLAN-2` where a cook expects a table
number, which is how they were noticed (`D-087`).

Run it deliberately::

    bench --site rpos.localhost execute restaurant_pos.setup.demo_cleanup.clean

**It refuses to run on the suite's site.** Those exact names are the fixtures
`setup/test_fixtures.py` builds, and the tests are written against them: running
this there would delete the ground the whole suite stands on.

**It never removes anything with money attached.** An order that reached a Sales
Invoice is left where it is, and says so. Test data and accounting records are
not the same thing, and only one of them is safe to delete.
"""

import frappe

#: Documents whose names or titles mark them as smoke-test leftovers.
RESIDUE_PATTERNS = ("RPOS-TEST-%", "RPOS-PLAN-%", "RPOS Test%", "E2E %")

#: The POS Profile `setup/test_fixtures.py` builds. Its presence means this is
#: the site the suite runs against, where the residue is not residue.
TEST_SITE_MARKER = "RPOS Test Terminal"


class Report:
	"""What went, and what would not."""

	def __init__(self):
		self.removed: dict[str, int] = {}
		self.kept: list[str] = []

	def gone(self, doctype: str, count: int = 1) -> None:
		if count:
			self.removed[doctype] = self.removed.get(doctype, 0) + count

	def spared(self, why: str) -> None:
		self.kept.append(why)

	def print(self) -> None:
		print("=== removed ===")
		for doctype, count in sorted(self.removed.items()):
			print(f"  {doctype}: {count}")
		if not self.removed:
			print("  (nothing — already clean)")

		print("\n=== kept ===")
		for why in self.kept:
			print(f"  {why}")
		if not self.kept:
			print("  (nothing was in the way)")


def clean() -> None:
	"""Delete the residue, children first. Idempotent."""
	if frappe.db.exists("POS Profile", TEST_SITE_MARKER):
		frappe.throw(
			f"This site carries {TEST_SITE_MARKER}, so RPOS-TEST-* documents are the "
			"test suite's fixtures rather than residue. Refusing to delete them."
		)

	report = Report()

	_drop_test_traffic(report)
	_drop_e2e_printing(report)
	_tidy_printers(report)
	_drop_items(report)
	_drop_tables(report)
	_drop_production_centers(report)
	_drop_sections(report)

	frappe.db.commit()
	report.print()

	print(
		"\nNote: the company is named 'Ruzmh Test Co' but is NOT residue — it is the "
		"demo's only company, and owns every account, warehouse and invoice on the "
		"site. Renaming it is a separate, deliberate operation."
	)


# --------------------------------------------------------------------------- #
# The orders standing on top of it
# --------------------------------------------------------------------------- #


def _drop_test_traffic(report: Report) -> None:
	"""Remove the unpaid orders that reference residue, and their tickets.

	They have to go first: an item or a table with an order pointing at it is
	not deletable, and Frappe raises rather than cascading.
	"""
	blocking = set()

	for pattern in RESIDUE_PATTERNS:
		blocking.update(
			frappe.get_all(
				"Restaurant Order Item",
				filters={"item": ("like", pattern)},
				pluck="parent",
				distinct=True,
			)
		)

	blocking.update(
		frappe.get_all(
			"Restaurant Order",
			filters={"table": ("in", _residue_tables() or [""])},
			pluck="name",
		)
	)

	for order_name in sorted(blocking):
		order = frappe.db.get_value(
			"Restaurant Order", order_name, ["name", "status", "sales_invoice", "table"], as_dict=True
		)
		if not order:
			continue

		if order.sales_invoice:
			# The money is real even when the item was not. Deleting this would
			# leave an invoice pointing at nothing.
			report.spared(f"{order.name} — settled as {order.sales_invoice}")
			continue

		kots = frappe.get_all("Kitchen Order Ticket", filters={"restaurant_order": order.name}, pluck="name")
		for kot in kots:
			frappe.delete_doc("Kitchen Order Ticket", kot, force=True, ignore_permissions=True)
		report.gone("Kitchen Order Ticket", len(kots))

		# The table points back at the order; clear it or the delete is refused.
		if order.table:
			frappe.db.set_value(
				"Restaurant Table",
				order.table,
				{"current_order": None, "status": "available"},
				update_modified=False,
			)

		frappe.delete_doc("Restaurant Order", order.name, force=True, ignore_permissions=True)
		report.gone("Restaurant Order")


def _residue_tables() -> list[str]:
	found = []
	for pattern in RESIDUE_PATTERNS:
		found += frappe.get_all("Restaurant Table", filters={"table_number": ("like", pattern)}, pluck="name")
	return found


# --------------------------------------------------------------------------- #
# The residue itself
# --------------------------------------------------------------------------- #


def _drop_e2e_printing(report: Report) -> None:
	"""The printer and agent the end-to-end check created, and their jobs."""
	printers = frappe.get_all("POS Printer", filters={"title": ("like", "E2E %")}, pluck="name")
	for printer in printers:
		jobs = frappe.get_all("POS Print Job", filters={"printer": printer}, pluck="name")
		for job in jobs:
			frappe.delete_doc("POS Print Job", job, force=True, ignore_permissions=True)
		report.gone("POS Print Job", len(jobs))

		frappe.delete_doc("POS Printer", printer, force=True, ignore_permissions=True)
		report.gone("POS Printer")

	for agent in frappe.get_all("POS Print Agent", filters={"title": ("like", "E2E %")}, pluck="name"):
		# on_trash takes the agent's user with it.
		frappe.delete_doc("POS Print Agent", agent, force=True, ignore_permissions=True)
		report.gone("POS Print Agent")


#: What has to go before an Item can, and the field that points at it.
ITEM_DEPENDENTS = (
	("Item Price", "item_code"),
	("POS Printer Routing Rule", "item"),
	("Restaurant Modifier Group Item", "item"),
)


def _tidy_printers(report: Report) -> None:
	"""Leave one printer per name, each owned by an agent, and an empty queue.

	Three things accumulate here and each is a trap of its own before a real
	printer is plugged in:

	* a printer nobody made deliberately — an English name among Arabic ones,
	  duplicating another's address, and often the one a station points at;
	* a station pointing at it, which is how a ticket goes to the wrong roll;
	* **a queue of jobs waiting for an agent that never ran.** That is the worst
	  of the three: the moment a real agent connects it prints the lot.
	"""
	from restaurant_pos.setup.demo import PRINTERS

	shipped = {spec["title"] for spec in PRINTERS}

	for printer in frappe.get_all("POS Printer", fields=["name", "title", "branch"]):
		if printer.title in shipped:
			continue

		# A station pointing at a printer about to go would be left with none,
		# and BR-070 level 7 would quietly send its food to the cashier.
		replacement = frappe.db.get_value(
			"POS Printer", {"title": "طابعة المشاوي", "branch": printer.branch}, "name"
		)
		for center in frappe.get_all("Production Center", filters={"printer": printer.name}, pluck="name"):
			frappe.db.set_value("Production Center", center, "printer", replacement)
			report.spared(f"{center} repointed to {replacement or 'no printer'}")

		for job in frappe.get_all("POS Print Job", filters={"printer": printer.name}, pluck="name"):
			frappe.db.set_value("POS Print Job", job, "status", "failed", update_modified=False)
			frappe.delete_doc("POS Print Job", job, force=True, ignore_permissions=True)
			report.gone("POS Print Job")

		frappe.db.set_value("POS Profile", {"default_printer": printer.name}, "default_printer", None)
		frappe.delete_doc("POS Printer", printer.name, force=True, ignore_permissions=True)
		report.gone("POS Printer")

	# Everything still waiting for an agent that has never run. Left alone, the
	# first real agent to connect would print all of it (`D-108` stops that at
	# claim time too, but a queue of hundreds is not what a first test wants).
	waiting = frappe.get_all("POS Print Job", filters={"status": "queued"}, pluck="name")
	for job in waiting:
		frappe.delete_doc("POS Print Job", job, force=True, ignore_permissions=True)
	report.gone("POS Print Job", len(waiting))


def _drop_items(report: Report) -> None:
	for item in frappe.get_all("Item", filters={"name": ("like", "RPOS-TEST-%")}, pluck="name"):
		if frappe.db.count("Sales Invoice Item", {"item_code": item}):
			report.spared(f"{item} — sold on an invoice")
			continue

		for doctype, field in ITEM_DEPENDENTS:
			if not frappe.db.exists("DocType", doctype):
				continue
			for row in frappe.get_all(doctype, filters={field: item}, pluck="name"):
				frappe.delete_doc(doctype, row, force=True, ignore_permissions=True)
				report.gone(doctype)

		frappe.delete_doc("Item", item, force=True, ignore_permissions=True)
		report.gone("Item")


def _drop_tables(report: Report) -> None:
	for table in _residue_tables():
		if frappe.db.count("Restaurant Order", {"table": table}):
			report.spared(f"{table} — an order still points at it")
			continue

		for kot in frappe.get_all("Kitchen Order Ticket", filters={"table": table}, pluck="name"):
			frappe.db.set_value("Kitchen Order Ticket", kot, "table", None, update_modified=False)

		frappe.delete_doc("Restaurant Table", table, force=True, ignore_permissions=True)
		report.gone("Restaurant Table")


def _drop_production_centers(report: Report) -> None:
	for center in frappe.get_all(
		"Production Center", filters={"title": ("like", "RPOS Test%")}, pluck="name"
	):
		if frappe.db.count("Kitchen Order Ticket", {"production_center": center}):
			report.spared(f"{center} — a kitchen ticket was raised for it")
			continue

		for rule in frappe.get_all(
			"POS Printer Routing Rule", filters={"production_center": center}, pluck="name"
		):
			frappe.delete_doc("POS Printer Routing Rule", rule, force=True, ignore_permissions=True)
			report.gone("POS Printer Routing Rule")

		frappe.delete_doc("Production Center", center, force=True, ignore_permissions=True)
		report.gone("Production Center")


def _drop_sections(report: Report) -> None:
	for section in frappe.get_all(
		"Restaurant Section", filters={"title": ("like", "RPOS Test%")}, pluck="name"
	):
		remaining = frappe.db.count("Restaurant Table", {"section": section})
		if remaining:
			report.spared(f"{section} — {remaining} table(s) still in it")
			continue

		if frappe.db.count("POS Profile", {"restaurant_section": section}):
			report.spared(f"{section} — a terminal is configured for it")
			continue

		frappe.delete_doc("Restaurant Section", section, force=True, ignore_permissions=True)
		report.gone("Restaurant Section")

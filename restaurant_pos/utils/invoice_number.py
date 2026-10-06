# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Invoice numbers: the branch, then the terminal, then a count (`D-308`, `D-309`).

    1002-01-000001
    branch · terminal · count

**One counter for the whole company is one queue.** ERPNext locks the series
row from the insert until the transaction ends, so every till on a shared
series sells one after another: ten tills hammering one counter took 5.3 s a
sale on the rehearsal site, and 0.9 s with a counter each (`docs/14` §5.3).
ZATCA counts per device anyway.

**Through `naming_series`, never by setting the name.** A name put on the
document by hand made ERPNext write the recipe rows twice — measured, and it
would have doubled the stock a posting takes.

**The counter row is made when the terminal is defined**, not at its first
sale: two tills creating their rows in the same instant deadlock on the gap.

Both numbers are filled in for whoever does not care, typed by whoever has a
scheme of their own, refused when taken, and locked once the terminal has sold.

Refs: `docs/14_POS_Posting_Design.md` §5.3
"""

import frappe
from frappe import _
from frappe.model.naming import NamingSeries
from frappe.query_builder.functions import Max
from frappe.utils import cint

from restaurant_pos.utils.order import branch_of_profile, profiles_in, table_section_branch

BRANCH_NUMBER = "rpos_branch_number"
DEVICE_NUMBER = "rpos_device_number"

#: Where the automatic numbers start, and how wide a terminal's is written.
FIRST_BRANCH = 1001
FIRST_DEVICE = 1
DEVICE_WIDTH = 2

#: Six digits: a terminal selling a thousand bills a day runs for 2.7 years.
COUNT = ".######"

#: What else counts on the terminal's own series, and the prefix that tells it
#: apart: an order is `RO-1002-01-000001` (`D-310`). Its short daily number is
#: what the guest hears; this is the name the office reads.
ORDER_PREFIX = "RO-"
NUMBERED_PER_TERMINAL = (("Sales Invoice", ""), ("Restaurant Order", ORDER_PREFIX))


def number_branch(doc, method=None) -> None:
	"""`Branch.validate` — give the branch its number, or check the one typed."""
	typed = _digits(doc.get(BRANCH_NUMBER), _("Branch Number"))
	others = _branch_numbers(apart_from=doc.name)

	if not typed:
		doc.set(BRANCH_NUMBER, str(_next_free(others, FIRST_BRANCH)))
		return

	doc.set(BRANCH_NUMBER, typed)
	if cint(typed) in others:
		frappe.throw(
			_("Branch Number {0} belongs to {1}. Choose another.").format(typed, others[cint(typed)]),
			title=_("Number Taken"),
		)

	before = doc.get_doc_before_save()
	was = before.get(BRANCH_NUMBER) if before else None
	if was and cint(was) != cint(typed) and _has_sold(profiles_in(doc.name)):
		frappe.throw(
			_(
				"Branch Number cannot change from {0}: this branch has invoices numbered with it, "
				"and the sequence would break."
			).format(was),
			title=_("Number In Use"),
		)


def number_device(doc, method=None) -> None:
	"""`POS Profile.validate` — give the terminal its number within its branch."""
	branch = table_section_branch(doc.get("restaurant_section"))
	if not branch:
		# Not one of our tills: an ERPNext POS Profile nobody gave a section.
		return

	typed = _digits(doc.get(DEVICE_NUMBER), _("Device Number"))
	others = _device_numbers(branch, apart_from=doc.name)

	if not typed:
		doc.set(DEVICE_NUMBER, _padded(_next_free(others, FIRST_DEVICE)))
		return

	doc.set(DEVICE_NUMBER, _padded(typed))
	if cint(typed) in others:
		frappe.throw(
			_("Device Number {0} belongs to {1} in this branch. Choose another.").format(
				_padded(typed), others[cint(typed)]
			),
			title=_("Number Taken"),
		)

	before = doc.get_doc_before_save()
	was = before.get(DEVICE_NUMBER) if before else None
	if was and cint(was) != cint(typed) and _has_sold([doc.name]):
		frappe.throw(
			_(
				"Device Number cannot change from {0}: this terminal has invoices numbered with it, "
				"and the sequence would break."
			).format(was),
			title=_("Number In Use"),
		)


def make_counter(doc, method=None) -> None:
	"""`POS Profile.on_update` — the terminal's counters exist before it sells."""
	_ensure_counters(series_for(doc.name, number_now=False))


def order_series_for(pos_profile: str | None) -> str | None:
	"""The naming series a terminal's orders take: its invoice series behind `RO-`."""
	series = series_for(pos_profile)
	return ORDER_PREFIX + series if series else None


def series_for(pos_profile: str | None, *, number_now: bool = True) -> str | None:
	"""The naming series a terminal's invoices take, or None for a terminal that is not ours.

	A terminal from before this existed is numbered here, the first time it is
	asked — once, and then it is simply read.
	"""
	branch = branch_of_profile(pos_profile)
	if not branch:
		return None

	branch_number = frappe.db.get_value("Branch", branch, BRANCH_NUMBER)
	device_number = frappe.db.get_value("POS Profile", pos_profile, DEVICE_NUMBER)

	numbered_here = not (branch_number and device_number)
	if numbered_here:
		if not number_now:
			return None
		branch_number = branch_number or _number_branch_now(branch)
		device_number = device_number or _number_device_now(pos_profile, branch)

	series = f"{branch_number}-{device_number}-{COUNT}"
	if numbered_here:
		_ensure_counters(series)
	return series


def number_existing() -> None:
	"""Number every branch and terminal that has none, oldest first (the patch, and a restore)."""
	for branch in frappe.get_all(
		"Branch", filters={BRANCH_NUMBER: ("in", ("", None))}, pluck="name", order_by="creation"
	):
		_number_branch_now(branch)

	for profile in frappe.get_all(
		"POS Profile",
		filters={"restaurant_section": ("is", "set")},
		pluck="name",
		order_by="creation",
	):
		# Counters too, whether or not the numbers are new: a terminal numbered
		# before orders took its series has an invoice counter and no order one.
		_ensure_counters(series_for(profile))


def restart_counters() -> None:
	"""After the books are cleared, each terminal counts on from the last document still standing."""
	for profile in frappe.get_all("POS Profile", filters={DEVICE_NUMBER: ("is", "set")}, pluck="name"):
		series = series_for(profile, number_now=False)
		if not series:
			continue
		for doctype, lead in NUMBERED_PER_TERMINAL:
			naming = NamingSeries(lead + series)
			prefix = naming.get_prefix()
			table = frappe.qb.DocType(doctype)
			last = (
				frappe.qb.from_(table)
				.select(Max(table.name))
				.where(table.name.like(f"{prefix}%"))
				.run()[0][0]
			)
			naming.update_counter(cint(last[len(prefix) :]) if last else 0)


# --------------------------------------------------------------------------- #


def _digits(value, label: str) -> str:
	typed = (value or "").strip()
	if typed and not typed.isdigit():
		frappe.throw(_("{0} is digits only: {1} is not a number.").format(label, typed))
	return typed


def _padded(number) -> str:
	return str(cint(number)).zfill(DEVICE_WIDTH)


def _next_free(taken: dict[int, str], first: int) -> int:
	number = first
	while number in taken:
		number += 1
	return number


def _branch_numbers(apart_from: str | None = None) -> dict[int, str]:
	rows = frappe.get_all("Branch", filters={BRANCH_NUMBER: ("is", "set")}, fields=["name", BRANCH_NUMBER])
	return {cint(row[BRANCH_NUMBER]): row.name for row in rows if row.name != apart_from}


def _device_numbers(branch: str, apart_from: str | None = None) -> dict[int, str]:
	terminals = [name for name in profiles_in(branch) if name != apart_from]
	if not terminals:
		return {}
	rows = frappe.get_all(
		"POS Profile",
		filters={"name": ("in", terminals), DEVICE_NUMBER: ("is", "set")},
		fields=["name", DEVICE_NUMBER],
	)
	return {cint(row[DEVICE_NUMBER]): row.name for row in rows}


def _number_branch_now(branch: str) -> str:
	number = str(_next_free(_branch_numbers(apart_from=branch), FIRST_BRANCH))
	frappe.db.set_value("Branch", branch, BRANCH_NUMBER, number, update_modified=False)
	return number


def _number_device_now(pos_profile: str, branch: str) -> str:
	number = _padded(_next_free(_device_numbers(branch, apart_from=pos_profile), FIRST_DEVICE))
	frappe.db.set_value("POS Profile", pos_profile, DEVICE_NUMBER, number, update_modified=False)
	return number


def _has_sold(profiles: list[str]) -> bool:
	return bool(profiles) and bool(frappe.db.exists("Sales Invoice", {"pos_profile": ("in", profiles)}))


def _ensure_counters(series: str | None) -> None:
	"""Make the counter rows of one terminal — now, so no sale ever makes one."""
	if not series:
		return
	for _doctype, prefix in NUMBERED_PER_TERMINAL:
		naming = NamingSeries(prefix + series)
		if frappe.db.get_value("Series", naming.get_prefix(), "name", order_by="name") is None:
			naming.update_counter(0)

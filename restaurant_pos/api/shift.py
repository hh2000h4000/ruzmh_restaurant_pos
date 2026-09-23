# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Whitelisted shift endpoints — the business day and the tills inside it.

Thin by design (``02_backend_rules.md``): parse, authorise, delegate to
``utils.shift``, return JSON.

Refs: 07_API_Design.md, FR-8.1..8.3, BR-040..BR-045, D-047
"""

import frappe
from frappe import _
from frappe.utils import cint

from restaurant_pos.utils import cash_movement, idempotency, printing
from restaurant_pos.utils import shift as service


@frappe.whitelist()
def get_state(pos_profile: str) -> dict:
	"""Both levels: is the day open, is a drawer taken, and is it mine (FR-8.1)."""
	return service.shift_state(pos_profile)


@frappe.whitelist()
def get_day_summary(shift: str) -> dict:
	"""The day's report (FR-8.3). Read-only, so no ``queue_id``."""
	return service.summarise(shift)


@frappe.whitelist()
def get_till_summary(opening_entry: str, for_counting: int = 0) -> dict:
	"""One drawer's takings, and what closing it will be measured against.

	**The drawer opens only when somebody is about to count it** (`D-093`,
	`D-237`). The closing screen asks with `for_counting`, because the cashier
	is standing there with the cash and `close_till` would be too late — by then
	the count has been typed in. Reading the same figures on screen is not that:
	a cashier checking the X report mid-shift, or a manager looking over their
	shoulder, must not pop the drawer in front of a queue.

	One endpoint for one question, with the side effect named at the call site,
	rather than two that answer the same thing and drift (`CLAUDE.md` §5.5).
	"""
	summary = service.summarise_till(opening_entry)

	if cint(for_counting):
		pos_profile = frappe.db.get_value("POS Opening Entry", opening_entry, "pos_profile")
		printing.open_drawer(pos_profile, reason="counting the till")

	return summary


@frappe.whitelist()
def print_till_report(opening_entry: str, queue_id: str | None = None) -> dict:
	"""The drawer's financial report on paper, now — X while it is open (FR-8.3, `D-219`).

	The user's customers print it before a cashier steps away for five minutes
	and again when they come back, and compare the two: the one check a shared
	drawer has on it.

	**Refuses before promising** (`D-148`). The print runs off the request, so
	nothing downstream could tell the cashier that this terminal has no printer,
	and the screen would say "sent" over a queue that produced nothing.
	"""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	# Read first, which checks the branch as the summary endpoint does — the
	# figures on the paper are the ones the screen may show this person.
	service.summarise_till(opening_entry)
	pos_profile = frappe.db.get_value("POS Opening Entry", opening_entry, "pos_profile")
	if not printing.receipt_printer(pos_profile):
		frappe.throw(_("No printer is linked to this terminal, so nothing can be printed."))

	printing.enqueue_print("print_shift_report", pos_profile=pos_profile, opening_entry=opening_entry)

	result = {"opening_entry": opening_entry, "queued": True}
	idempotency.remember(
		queue_id,
		"print_till_report",
		result,
		reference_doctype="POS Opening Entry",
		reference_name=opening_entry,
	)
	return result


@frappe.whitelist()
def open_day(pos_profile: str, title: str | None = None, queue_id: str | None = None) -> dict:
	"""Start the branch's day (FR-8.1)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	result = service.open_day(pos_profile=pos_profile, title=title)
	idempotency.remember(
		queue_id, "open_day", result, reference_doctype="Restaurant Shift", reference_name=result["shift"]
	)
	return result


@frappe.whitelist()
def open_till(
	pos_profile: str,
	opening_floats: dict | str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Take the drawer, opening the day too if nobody has (FR-8.1)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	result = service.open_till(
		pos_profile=pos_profile,
		opening_floats=frappe.parse_json(opening_floats)
		if isinstance(opening_floats, str)
		else opening_floats,
	)
	idempotency.remember(
		queue_id,
		"open_till",
		result,
		reference_doctype="POS Opening Entry",
		reference_name=result["entry"],
	)
	return result


@frappe.whitelist()
def close_till(
	opening_entry: str,
	counted: dict | str | None = None,
	variance_reason: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Hand the drawer back and account for it (FR-8.2)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	result = service.close_till(
		opening_entry=opening_entry,
		counted=frappe.parse_json(counted) if isinstance(counted, str) else counted,
		variance_reason=variance_reason,
	)
	idempotency.remember(
		queue_id,
		"close_till",
		result,
		reference_doctype="POS Closing Entry",
		reference_name=result["closing_entry"],
	)
	return result


@frappe.whitelist()
def close_day(
	shift: str,
	force: int | bool = 0,
	pos_profile: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""End of day — any drawer left open is closed at its expected figures.

	`pos_profile` names the terminal it was closed from, for the audit rows the
	close writes (`D-178`). Optional, because a queued replay from an older
	client will not carry it and a day must still be closable.
	"""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	result = service.close_day(shift_name=shift, force=bool(int(force or 0)), pos_profile=pos_profile)
	idempotency.remember(
		queue_id, "close_day", result, reference_doctype="Restaurant Shift", reference_name=shift
	)
	return result


@frappe.whitelist(methods=["POST"])
def move_drawer_cash(
	pos_profile: str,
	direction: str,
	amount: float,
	reason: str,
	mode_of_payment: str | None = None,
	override_token: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Notes in or out of the open drawer for something that is not a sale (`D-245`).

	**POST only, and idempotent.** Money that moves twice because a tap was
	repeated is the defect this whole record exists to prevent.
	"""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	result = cash_movement.record(
		pos_profile,
		direction=direction,
		amount=amount,
		reason=reason,
		mode_of_payment=mode_of_payment,
		override_token=override_token,
	)
	idempotency.remember(
		queue_id,
		"move_drawer_cash",
		result,
		reference_doctype="POS Cash Movement",
		reference_name=result["movement"],
	)
	return result

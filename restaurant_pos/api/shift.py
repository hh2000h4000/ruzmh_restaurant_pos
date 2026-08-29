# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Whitelisted shift endpoints — the business day and the tills inside it.

Thin by design (``02_backend_rules.md``): parse, authorise, delegate to
``utils.shift``, return JSON.

Refs: 07_API_Design.md, FR-8.1..8.3, BR-040..BR-045, D-047
"""

import frappe

from restaurant_pos.utils import idempotency
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
def get_till_summary(opening_entry: str) -> dict:
	"""One drawer's takings, and what closing it will be measured against."""
	return service.summarise_till(opening_entry)


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
def close_day(shift: str, force: int | bool = 0, queue_id: str | None = None) -> dict:
	"""End of day — any drawer left open is closed at its expected figures."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	result = service.close_day(shift_name=shift, force=bool(int(force or 0)))
	idempotency.remember(
		queue_id, "close_day", result, reference_doctype="Restaurant Shift", reference_name=shift
	)
	return result

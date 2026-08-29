# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Whitelisted shift endpoints.

Thin by design (``02_backend_rules.md``): parse, authorise, delegate to
``utils.shift``, return JSON.

Refs: 07_API_Design.md, FR-8.1..8.3, BR-040..BR-045
"""

import frappe

from restaurant_pos.utils import idempotency
from restaurant_pos.utils import shift as service


@frappe.whitelist()
def get_state(pos_profile: str) -> dict:
	"""Is a shift open on this terminal, whose, and may I close it (FR-8.1)."""
	return service.shift_state(pos_profile)


@frappe.whitelist()
def get_summary(shift: str) -> dict:
	"""The shift report (FR-8.3). Read-only, so no ``queue_id``."""
	return service.summarise(shift)


@frappe.whitelist()
def open_shift(
	pos_profile: str,
	opening_floats: dict | str | None = None,
	title: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Start selling (FR-8.1)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	result = service.open_shift(
		pos_profile=pos_profile,
		opening_floats=frappe.parse_json(opening_floats)
		if isinstance(opening_floats, str)
		else opening_floats,
		title=title,
	)

	idempotency.remember(
		queue_id, "open_shift", result, reference_doctype="Restaurant Shift", reference_name=result["shift"]
	)
	return result


@frappe.whitelist()
def close_shift(
	shift: str,
	counted: dict | str | None = None,
	variance_reason: str | None = None,
	force: int | bool = 0,
	queue_id: str | None = None,
) -> dict:
	"""Finish the day and reconcile the drawer (FR-8.2)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	result = service.close_shift(
		shift_name=shift,
		counted=frappe.parse_json(counted) if isinstance(counted, str) else counted,
		variance_reason=variance_reason,
		force=bool(int(force or 0)),
	)

	idempotency.remember(
		queue_id, "close_shift", result, reference_doctype="Restaurant Shift", reference_name=shift
	)
	return result

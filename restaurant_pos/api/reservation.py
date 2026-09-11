# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Whitelisted reservation endpoints.

Thin by design (``02_backend_rules.md``): parse, authorise, delegate to
``utils.reservation``, return JSON. Every endpoint that changes something is
replay-safe on ``queue_id`` (``09`` §8).

**Who may act.** Taking, changing, seating, cancelling and marking a no-show
are the host's job in every system studied — Toast, OpenTable, SevenRooms — and
none of them puts a permission in front of it. So any till role may, in its own
branch; somebody with no till role may not. Every change is kept on the
record's own history with the user who made it (`D-191`).

Refs: FR-14, BR-090..BR-094, D-191
"""

import frappe
from frappe import _

from restaurant_pos.utils import idempotency
from restaurant_pos.utils import reservation as service
from restaurant_pos.utils.order import branch_of_profile
from restaurant_pos.utils.permissions import get_pos_permission_set, validate_branch_access

DOCTYPE = "Restaurant Reservation"


def _assert_till_role() -> None:
	if not get_pos_permission_set().roles:
		frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)


def _branch_of_terminal(pos_profile: str) -> str:
	branch = branch_of_profile(pos_profile)
	if not branch:
		frappe.throw(_("POS Profile {0} has no Restaurant Section configured.").format(pos_profile))

	validate_branch_access(branch)
	_assert_till_role()
	return branch


def _authorise(name: str) -> None:
	branch = frappe.db.get_value(DOCTYPE, name, "branch")
	if not branch:
		frappe.throw(_("Reservation {0} does not exist.").format(name))

	validate_branch_access(branch)
	_assert_till_role()


@frappe.whitelist()
def list_reservations(pos_profile: str, date: str | None = None) -> list[dict]:
	"""A day's bookings in this terminal's branch, in the order guests arrive."""
	return service.listing(_branch_of_terminal(pos_profile), date)


@frappe.whitelist()
def save_reservation(pos_profile: str, reservation: dict | str, queue_id: str | None = None) -> dict:
	"""Take a booking, or change one still expected (`FR-14.1`)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	data = frappe.parse_json(reservation) if isinstance(reservation, str) else reservation
	if data.get("name"):
		_authorise(data["name"])

	result = service.save(data, branch=_branch_of_terminal(pos_profile))

	idempotency.remember(
		queue_id, "save_reservation", result, reference_doctype=DOCTYPE, reference_name=result["reservation"]
	)
	return result


@frappe.whitelist()
def seat_reservation(
	name: str,
	pos_profile: str,
	order_type: str,
	table: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""The party has arrived: open their bill at their table (`FR-14.3`)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	_authorise(name)
	_branch_of_terminal(pos_profile)
	result = service.seat(name, pos_profile=pos_profile, order_type=order_type, table=table)

	idempotency.remember(
		queue_id,
		"seat_reservation",
		result,
		reference_doctype="Restaurant Order",
		reference_name=result["order_name"],
	)
	return result


@frappe.whitelist()
def cancel_reservation(name: str, reason: str, queue_id: str | None = None) -> dict:
	"""`FR-14.4` — cancelled, with the reason the guest gave."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	_authorise(name)
	result = service.cancel(name, reason)

	idempotency.remember(
		queue_id, "cancel_reservation", result, reference_doctype=DOCTYPE, reference_name=name
	)
	return result


@frappe.whitelist()
def mark_no_show(name: str, queue_id: str | None = None) -> dict:
	"""The party did not come. Also done for everyone left when the day closes."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	_authorise(name)
	result = service.no_show(name)

	idempotency.remember(queue_id, "mark_no_show", result, reference_doctype=DOCTYPE, reference_name=name)
	return result

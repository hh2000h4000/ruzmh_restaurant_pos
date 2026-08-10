# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Kitchen Order Tickets.

``FR-6.3``: group the order's items by their resolved Production Center and
raise one KOT per center. ``BR-073`` defines the four types — initial,
addition, void, reprint.

This module creates the documents and announces them. **It does not print.**
The ESC/POS service, the 5-second timeout and the fallback printer are Phase 3
(``FR-7.3``, ``BR-072``); every KOT is left at ``print_status = pending`` for it
to pick up.

Prices never appear on a KOT (``BR-075``). The header carries order number,
table, order type, cashier and timestamp (``BR-074``).

Refs: BR-073, BR-074, BR-075, FR-2.3, FR-2.4, FR-2.5, FR-6.3, FR-6.4
"""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from restaurant_pos.utils.audit import log_audit

#: Lines that still have to reach the kitchen.
PENDING = "pending"
SENT = "sent"
VOID = "void"


def send_to_kitchen(order, *, kot_type: str | None = None) -> dict:
	"""Raise a KOT per production center for everything not yet sent.

	Returns the created tickets plus any items that no rule could route, which
	fall to the cashier's printer under ``BR-070`` level 7.
	"""
	pending = [row for row in order.items if row.status == PENDING]
	if not pending:
		frappe.throw(_("There is nothing new to send to the kitchen."))

	kot_type = kot_type or _kot_type_for(order)
	header = _header(order)

	routed, unrouted = _split_by_center(pending)
	created = []

	for production_center, rows in routed.items():
		kot = _create_kot(
			order,
			kot_type=kot_type,
			production_center=production_center,
			rows=rows,
			header=header,
			action="add",
		)
		created.append(kot)

		for row in rows:
			row.kot_reference = kot.name

	moment = now_datetime()
	for row in pending:
		row.status = SENT
		row.sent_at = moment

	if order.status in ("draft", "active"):
		order.status = "in_kitchen"

	order.save(ignore_permissions=True)

	for kot in created:
		_announce(kot)

	return {
		"kots_created": [
			{
				"kot_name": kot.name,
				"production_center": kot.production_center,
				"kot_type": kot.kot_type,
				"print_status": kot.print_status,
			}
			for kot in created
		],
		# BR-070 level 7. Surfaced rather than swallowed: an item nobody routed
		# is an item no kitchen station is cooking.
		"unrouted_items": [row.item_name for row in unrouted],
	}


def create_void_kot(order, rows) -> list[dict]:
	"""Tell the kitchen to drop lines it has already been given (BR-013).

	Called when a line that reached the kitchen is voided, and for every sent
	line when the whole order is cancelled.
	"""
	rows = [row for row in rows if row.kot_reference or row.sent_at]
	if not rows:
		return []

	header = _header(order)
	routed, _unrouted = _split_by_center(rows)

	created = []
	for production_center, center_rows in routed.items():
		kot = _create_kot(
			order,
			kot_type="void",
			production_center=production_center,
			rows=center_rows,
			header=header,
			action="void",
		)
		created.append(kot)
		_announce(kot)

	return [
		{"kot_name": kot.name, "production_center": kot.production_center, "kot_type": "void"}
		for kot in created
	]


def reprint(kot_name: str) -> dict:
	"""Queue an existing ticket to be printed again (FR-6.4).

	No second document is created: a reprint is the same ticket on paper twice,
	and a duplicate would distort the kitchen's history. The trail lives in the
	audit log, and Phase 3 stamps the output with a REPRINT header
	(``DECISIONS.md`` D-021).
	"""
	kot = frappe.get_doc("Kitchen Order Ticket", kot_name)
	order = frappe.db.get_value(
		"Restaurant Order", kot.restaurant_order, ["branch", "pos_profile"], as_dict=True
	)

	kot.db_set("print_status", "pending", update_modified=False)

	log_audit(
		"reprint_receipt",
		branch=order.branch,
		pos_profile=order.pos_profile,
		restaurant_order=kot.restaurant_order,
		details={"kot": kot.name, "production_center": kot.production_center},
	)

	_announce(kot, reprint=True)
	return {"kot_name": kot.name, "print_status": "pending", "reprint": True}


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _kot_type_for(order) -> str:
	"""BR-073 — the first send is initial, anything after it is an addition."""
	already_sent = any(row.status in (SENT, VOID) and row.sent_at for row in order.items)
	return "addition" if already_sent else "initial"


def _header(order) -> frappe._dict:
	"""BR-074 — what the kitchen needs to identify the ticket.

	Arabic titles, because the kitchen reads the ticket and printing is
	Arabic-first (``FR-7.4``).
	"""
	return frappe._dict(
		order_type_title=frappe.db.get_value("Restaurant Order Type", order.order_type, "title_ar"),
		cashier_name=frappe.db.get_value("User", order.cashier, "full_name"),
		table=order.table,
	)


def _split_by_center(rows) -> tuple[dict, list]:
	"""Group rows by production center; unrouted rows come back separately."""
	routed: dict[str, list] = {}
	unrouted = []

	for row in rows:
		if row.production_center:
			routed.setdefault(row.production_center, []).append(row)
		else:
			unrouted.append(row)

	return routed, unrouted


def _create_kot(order, *, kot_type, production_center, rows, header, action):
	kot = frappe.get_doc(
		{
			"doctype": "Kitchen Order Ticket",
			"restaurant_order": order.name,
			"kot_type": kot_type,
			"production_center": production_center,
			"table": header.table,
			"order_type_title": header.order_type_title,
			"cashier_name": header.cashier_name,
			"sent_at": now_datetime(),
			"print_status": "pending",
			"items": [
				{
					"item": row.item,
					"item_name": row.item_name,
					"qty": flt(row.qty),
					"modifiers": row.modifiers,
					"notes": row.notes,
					"action": action,
				}
				for row in rows
			],
		}
	)
	kot.insert(ignore_permissions=True)
	return kot


def _announce(kot, *, reprint: bool = False) -> None:
	"""Push to the KDS channel for this production center (07 §9).

	Realtime is a notification, not the delivery mechanism: a KDS that missed
	the event still finds the ticket by querying.
	"""
	frappe.publish_realtime(
		event="rpos:new_kot",
		message={
			"kot": kot.name,
			"kot_type": kot.kot_type,
			"restaurant_order": kot.restaurant_order,
			"table": kot.table,
			"reprint": reprint,
		},
		room=f"rpos:pc:{kot.production_center}",
	)

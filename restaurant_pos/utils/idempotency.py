# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Replay protection for offline-queue actions.

``09_Offline_Synchronization.md`` §8 and ``CLAUDE.md`` §5.3: every API that
changes data accepts a ``queue_id`` and checks it before executing. Replaying
the same ``queue_id`` returns the previous result and never creates a second
document.

The queue flushes after an outage that may have lasted days, and it retries on
network failure. A payment replayed once is a duplicate invoice; an ``add_item``
replayed once is a line the customer did not order.

``Restaurant Order.offline_queue_id`` covers order creation only. Every other
action needs somewhere durable to record that it already ran, which is what
``POS Sync Entry`` is for — the cache is not durable enough for a 72-hour
offline window (``DECISIONS.md`` D-019).

Refs: 09 §8, CLAUDE.md §5.3
"""

import frappe


def previous_result(queue_id: str | None) -> dict | None:
	"""The stored response for ``queue_id``, or ``None`` if it is new."""
	if not queue_id:
		return None

	entry = frappe.db.get_value(
		"POS Sync Entry", {"queue_id": queue_id}, ["response", "reference_name"], as_dict=True
	)
	if not entry:
		return None

	result = frappe.parse_json(entry.response) if entry.response else {}
	if isinstance(result, dict):
		result = dict(result)
		result["already_processed"] = True

	return result


def remember(
	queue_id: str | None,
	action: str,
	response: dict,
	*,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> None:
	"""Record that ``queue_id`` has been handled, with what it returned."""
	if not queue_id:
		return

	frappe.get_doc(
		{
			"doctype": "POS Sync Entry",
			"queue_id": queue_id,
			"action": action,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			# Serialised here, not left to the field.
			#
			# Handing a dict to a text field makes Frappe reach for a plain
			# `json.dumps`, which has no encoder for a datetime and raises
			# "Object of type datetime is not JSON serializable" — a 500 from
			# whichever endpoint happened to return one. `close_till` did: its
			# report carries `opened_at`, so closing a shift failed at the last
			# step, after the drawer had already been counted.
			"response": frappe.as_json(response),
		}
	).insert(ignore_permissions=True)

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The whitelisted endpoint an offline sale replays through.

One call, because offline there is no server id to hang a conversation on — see
`utils/offline`. Replay-safe on `queue_id` like every other write, and that
matters more here than anywhere: this one carries a payment, and a payment
replayed once is a customer charged twice (09 §8).

Refs: 07_API_Design.md, 09 §5, §8, D-072
"""

import frappe

from restaurant_pos.utils import idempotency
from restaurant_pos.utils import offline as service
from restaurant_pos.utils.deadlock import retried
from restaurant_pos.utils.permissions import validate_branch_access


@frappe.whitelist()
@retried
def submit_order(pos_profile: str, payload: dict | str, queue_id: str) -> dict:
	"""Land a bill the till sold while the line was down (FR-2.1, 09 §5).

	`queue_id` is required rather than optional: an offline order **is** a
	replay, and one without an idempotency key is one that posts twice the first
	time a flush is interrupted mid-request.
	"""
	if not queue_id:
		frappe.throw(frappe._("An offline order needs its queue id."))

	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	section = frappe.db.get_value("POS Profile", pos_profile, "restaurant_section")
	branch = frappe.db.get_value("Restaurant Section", section, "branch") if section else None
	if branch:
		validate_branch_access(branch)

	result = service.submit_order(
		pos_profile=pos_profile,
		payload=frappe.parse_json(payload) if isinstance(payload, str) else payload,
		offline_queue_id=queue_id,
	)

	idempotency.remember(
		queue_id,
		"offline_submit_order",
		result,
		reference_doctype="Restaurant Order",
		reference_name=result["order_name"],
	)
	return result

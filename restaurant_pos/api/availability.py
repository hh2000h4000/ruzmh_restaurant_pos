# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""What is left and what is finished, for the tiles on the till (`D-321`, `D-322`)."""

import frappe
from frappe import _

from restaurant_pos.utils import availability as service
from restaurant_pos.utils import idempotency
from restaurant_pos.utils.deadlock import retried
from restaurant_pos.utils.order import branch_of_profile
from restaurant_pos.utils.permissions import validate_branch_access


def _branch(pos_profile: str) -> str:
	branch = branch_of_profile(pos_profile)
	if not branch:
		frappe.throw(_("POS Profile {0} has no Restaurant Section configured.").format(pos_profile))
	validate_branch_access(branch)
	return branch


@frappe.whitelist()
def get_stock(pos_profile: str) -> dict:
	"""Who is finished and who is running low in this terminal's branch."""
	_branch(pos_profile)
	return service.for_till(pos_profile)


@frappe.whitelist(methods=["POST"])
@retried
def set_sold_out(pos_profile: str, item: str, sold_out: int | bool = 1, queue_id: str | None = None) -> dict:
	"""Mark an item finished for today in this branch, or bring it back (`D-322`).

	Anybody working the till may: the person who hears "the soup is finished"
	is whoever stands there, and bringing it back is the same act undone. It
	moves no stock and no money; the row says who and when.
	"""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	branch = _branch(pos_profile)
	result = {"sold_out": service.set_sold_out(branch, item, bool(frappe.utils.cint(sold_out)))}
	idempotency.remember(queue_id, "set_sold_out", result, reference_doctype="Item", reference_name=item)
	return result

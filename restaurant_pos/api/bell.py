# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The bell on the till (`D-298`, `D-303`)."""

import frappe
from frappe import _

from restaurant_pos.utils import announcements
from restaurant_pos.utils import bell as service
from restaurant_pos.utils.order import branch_of_profile
from restaurant_pos.utils.permissions import validate_branch_access


@frappe.whitelist()
def get_bell(pos_profile: str, start: int = 0) -> dict:
	"""This branch's unprinted tickets and this cashier's announcements, a page at a time."""
	branch = branch_of_profile(pos_profile)
	if not branch:
		frappe.throw(_("POS Profile {0} has no Restaurant Section configured.").format(pos_profile))
	validate_branch_access(branch)
	return service.feed(branch, frappe.session.user, start=start)


@frappe.whitelist(methods=["POST"])
def mark_announcements_read(name: str | None = None) -> dict:
	"""The signed-in person read one announcement, or all of them (`D-303`).

	From the till's bell, or from the form opened in ERPNext's — which is why
	this asks for no till role: someone in the office reads announcements too.
	It can only ever touch the caller's own recipient rows. Idempotent by
	nature — reading twice records the first time — so it needs no `queue_id`.
	"""
	return {"marked": announcements.mark_read(frappe.session.user, name)}

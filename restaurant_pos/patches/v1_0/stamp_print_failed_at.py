"""Date the tickets that failed before `print_failed_at` existed (`D-298`).

The bell lists tickets by when they last failed. A ticket that failed earlier
is dated by its newest failed print job, or — when it never had one, because
its station had no printer — by when it was sent.
"""

import frappe


def execute():
	# Only tickets that ever failed: every printed ticket ever made is no business of this.
	ever = set(
		frappe.get_all(
			"POS Print Job",
			filters={"reference_doctype": "Kitchen Order Ticket", "status": "failed"},
			pluck="reference_name",
		)
	) | set(frappe.get_all("Kitchen Order Ticket", filters={"print_status": "failed"}, pluck="name"))

	for name in ever:
		if not frappe.db.exists("Kitchen Order Ticket", name) or frappe.db.get_value(
			"Kitchen Order Ticket", name, "print_failed_at"
		):
			continue
		failed = frappe.get_all(
			"POS Print Job",
			filters={"reference_doctype": "Kitchen Order Ticket", "reference_name": name, "status": "failed"},
			pluck="creation",
			order_by="creation desc",
			limit=1,
		)
		if failed:
			at = failed[0]
		elif frappe.db.get_value("Kitchen Order Ticket", name, "print_status") == "failed":
			at = frappe.db.get_value("Kitchen Order Ticket", name, "sent_at") or frappe.db.get_value(
				"Kitchen Order Ticket", name, "creation"
			)
		else:
			continue
		frappe.db.set_value("Kitchen Order Ticket", name, "print_failed_at", at, update_modified=False)

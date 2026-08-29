# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The short number a customer is told (FR-2.10).

An order has two numbers, and conflating them is the mistake this module exists
to avoid:

* ``Restaurant Order.name`` — ``RO-2026-08-00042``. Permanent, unique forever,
  the thing a refund or an audit is traced by. Never read out loud.
* ``daily_number`` — ``42``. Short, spoken, printed on the customer's copy, and
  **restarted** on a cycle the branch chooses. This is what every serious POS
  does, because "your order is twenty-one thousand two hundred and thirty-five"
  is not something a counter says.

**Scoped to the branch, not the terminal.** Two tills in one shop must never
both call "forty-two". Two shops may, and should — their customers are in
different rooms.

**Restart, not reuse.** Yesterday's 42 and today's 42 are different orders, and
what tells them apart is the record id, which never repeats.
"""

import frappe
from frappe.utils import cint, get_datetime

#: What the branch may choose. ``never`` keeps one running count for the branch,
#: for a shop that would rather have a number nobody repeats.
RESET_PERIODS = ("daily", "shift", "weekly", "monthly", "never")

DEFAULT_RESET = "daily"


def next_order_number(*, branch: str, shift: str | None, moment=None) -> int:
	"""Hand out the next number for this branch, and remember it.

	Race-safe by row lock: two tills creating an order in the same second take
	turns on one row rather than both reading 41 and both writing 42. The lock
	is held for the rest of the transaction, so it is released when the order
	saves or rolls back with it.
	"""
	if not branch:
		return 0

	key = period_key(reset_for(branch), moment=moment, shift=shift)
	name = f"{branch}-{key}"

	if not frappe.db.exists("POS Order Counter", name):
		try:
			frappe.get_doc(
				{
					"doctype": "POS Order Counter",
					"branch": branch,
					"period_key": key,
					"last_number": 0,
				}
			).insert(ignore_permissions=True)
		except frappe.DuplicateEntryError:
			# Another till created it between the check and the insert. Its row
			# is exactly the one we wanted; carry on and lock it below.
			pass

	current = frappe.db.get_value("POS Order Counter", name, "last_number", for_update=True)
	nxt = cint(current) + 1
	frappe.db.set_value("POS Order Counter", name, "last_number", nxt, update_modified=False)
	return nxt


def reset_for(branch: str) -> str:
	"""How often this branch restarts its numbering."""
	chosen = frappe.db.get_value("Branch", branch, "order_number_reset")
	return chosen if chosen in RESET_PERIODS else DEFAULT_RESET


def period_key(reset: str, *, moment=None, shift: str | None = None) -> str:
	"""Name the stretch of time this number belongs to.

	A string rather than a date so every period is one column and one lookup —
	an ISO week and a shift name have nothing else in common.
	"""
	moment = get_datetime(moment) if moment else frappe.utils.now_datetime()

	if reset == "never":
		return "all"
	if reset == "shift":
		# A shift that never opened has no key of its own; fall back to the day
		# rather than pooling every such order into one counter.
		return f"shift-{shift}" if shift else moment.strftime("%Y-%m-%d")
	if reset == "weekly":
		year, week, _day = moment.isocalendar()
		return f"{year}-W{week:02d}"
	if reset == "monthly":
		return moment.strftime("%Y-%m")

	return moment.strftime("%Y-%m-%d")

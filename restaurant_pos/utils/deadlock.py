# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""A till write that loses a deadlock is run once more (`D-369`).

Two tills writing at once can each hold a row the other wants; MariaDB ends
one of them with error 1213 and **rolls its whole transaction back**. The load
test hit it once in 8,488 `add_item`s: the order's line went in as Frappe saves
a child table — delete, then insert — beside another bill doing the same.

Nothing of the losing request is left in the database, so the honest answer is
to run it again from the top, once — what MariaDB's own manual advises. The
cashier then sees their line, not an error for a collision that was not theirs.

**Every endpoint that takes a `queue_id`** — the till's writes, the ones the
offline queue replays (`CLAUDE.md` §5.3) — carries it; `test_deadlock` refuses
one that does not. A second deadlock in a row is raised: that is load the retry
would only add to.
"""

import functools
import random
import time

import frappe


def retried(fn):
	@functools.wraps(fn)
	def wrapper(*args, **kwargs):
		try:
			return fn(*args, **kwargs)
		except frappe.QueryDeadlockError:
			# The transaction is already gone; this clears what Frappe holds for it —
			# the after-commit jobs, the cached values — so the second run starts clean.
			frappe.db.rollback()
			frappe.local.message_log = []
			frappe.local.rpos_permission_cache = {}
			# A few milliseconds apart, so the two tills do not meet again on the same row.
			time.sleep(random.uniform(0.02, 0.1))
			return fn(*args, **kwargs)

	return wrapper

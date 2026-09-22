# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Every shipped default has actually reached this site (`D-167`).

**This file exists because a rule that a person has to remember is a rule that
gets forgotten, and this one was forgotten twice.**

`setup/defaults.py` creates a `POS Permission Set` once and never touches it
again — right, because re-applying it on every migrate would put back a ceiling
a manager lowered on purpose. The cost is that a right added in a later version
never reaches a site installed before it: `bench migrate` adds the column, every
existing row is born holding `0`, and the shipped `1` never lands. The feature is
then invisible to the role it was written for, and nothing says why (`D-074`).

The fix is a patch, and the convention already existed — `grant_change_order_type`
did it in 2026. Then `can_split_bill` was added without one, and
`can_close_day_with_open_orders` after it, and **the suite stayed green through
both** because no test compares what the code ships to what a site holds. The
second one reached the user: on a branch that requires bills to be settled before
the day ends, nobody at all could close it.

So the gate does the remembering. The suite runs after `bench migrate`
(`wsl-verify.sh`), so every patch has run by the time this executes, and a right
added without one shows up here as a plain, named difference.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from restaurant_pos.setup.defaults import PERMISSION_SETS, QUICK_NOTES


class TheShippedDefaultsReachedThisSite(FrappeTestCase):
	def test_every_shipped_permission_set_holds_what_the_code_ships(self):
		"""A difference here means one of two things, and the message says both.

		Either a right was added to `setup/defaults.py` without the patch that
		carries it to existing sites — write one, next to
		`grant_missing_permission_defaults` — or a test changed a permission set
		and did not put it back, which is its own defect and worth the same
		red line.
		"""
		differences = []

		for role, shipped in PERMISSION_SETS.items():
			if not frappe.db.exists("POS Permission Set", role):
				# A site whose roles were never created is a different problem,
				# and not this test's to report.
				continue

			stored = frappe.db.get_value("POS Permission Set", role, list(shipped), as_dict=True)
			for field, wanted in shipped.items():
				# Compared as numbers: a `Check` comes back as `1` and a `Float`
				# ceiling as `10.0`, and `"10.0" != "10"` would report a
				# difference that is not one.
				if flt(stored.get(field)) != flt(wanted):
					differences.append(f"{role}.{field}: site={stored.get(field)} shipped={wanted}")

		self.assertEqual(
			differences,
			[],
			"The shipped defaults have not reached this site. Either a new right needs a "
			"patch to carry it to sites installed before it — see "
			"`patches/v1_0/grant_missing_permission_defaults.py` — or a test changed a "
			"permission set and left it changed.",
		)

	def test_the_ready_made_reasons_reached_this_site(self):
		"""D-239 — the same forgetting, one shape along.

		The reasons a cashier taps instead of typing ship in `QUICK_NOTES`, and
		that list runs on install only. Without `add_ready_made_reasons`, a site
		installed before them shows an empty row of chips and nobody can tell
		why. This says so by name.
		"""
		missing = [
			values["title"]
			for values in QUICK_NOTES
			if values["scope"] in ("void_reason", "cancel_reason")
			and not frappe.db.exists("POS Quick Note", {"scope": values["scope"]})
		]

		self.assertEqual(
			missing,
			[],
			"No ready-made reasons on this site. `patches/v1_0/add_ready_made_reasons.py` "
			"carries them to sites installed before them.",
		)

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Correct delivery-app payment methods shipped as bank transfers.

An earlier default created HungerStation, Jahez and Talabat as
``type = Bank``, which then demanded a company bank account before an invoice
could post. That was a misreading: the platform has already taken the
customer's money, so the sale is **credit** — the invoice stays outstanding
against the platform and the two settle on a monthly statement
(``DECISIONS.md`` D-029).

Only rows that still look exactly like the bad default are touched. A
restaurant that deliberately reconfigured one keeps its change.

Idempotent: a row already marked credit is skipped.
"""

import frappe

APPS = ("HungerStation", "Jahez", "Talabat")


def execute():
	for name in APPS:
		current = frappe.db.get_value(
			"Mode of Payment", name, ["type", "rpos_is_credit"], as_dict=True
		)
		if not current:
			continue

		if current.rpos_is_credit or current.type != "Bank":
			continue

		frappe.db.set_value(
			"Mode of Payment", name, {"type": "General", "rpos_is_credit": 1}, update_modified=False
		)

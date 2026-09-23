"""Give a running site the accounts its drawer-cash reasons post to (`D-246`).

`setup/cash_accounts` runs on install, like every other shipped default, so a
restaurant that already had RPOS would have the four reasons and nowhere for
them to land. Idempotent, and it never argues with a decision: an account that
exists is left alone and a reason that already names one keeps it.
"""

import frappe

from restaurant_pos.setup import cash_accounts


def execute():
	for company in frappe.get_all("Company", pluck="name"):
		cash_accounts.setup(company)

	frappe.db.commit()

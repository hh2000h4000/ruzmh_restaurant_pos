# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Which company a site-wide job works for, when nobody said (`D-273`).

**One rule, in one place.** It was written three times — twice as a private
`_the_only_company` and once without that half at all — and the copy without it
was `cash_accounts.setup`, which on a site with no default company set
anywhere would quietly create nothing. (The user's has none set, and its
accounts happened to exist already.)

**A global default is not always set**, and one company is not a guess; two
would be, and then this answers nothing rather than picking the wrong ledger.
"""

import frappe


def site_company(company: str | None = None) -> str | None:
	"""The company given, else the site's default, else its only one."""
	if company:
		return company

	default = frappe.defaults.get_global_default("company")
	if default:
		return default

	companies = frappe.get_all("Company", pluck="name", limit=2)
	return companies[0] if len(companies) == 1 else None

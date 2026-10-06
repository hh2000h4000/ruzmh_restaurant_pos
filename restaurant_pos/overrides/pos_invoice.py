# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""ERPNext's `POS Invoice`, with two of its questions asked our way (`D-312`).

A till sale is a `POS Invoice` (`D-308`), and ERPNext's controller is still
what builds it: the taxes, the totals, the recipe rows, the document a ZATCA
integration signs. Two of its checks cannot stay as they are **on our
terminals**, and both are replaced here rather than worked around:

* **Is the drawer open?** ERPNext asks with `frappe.get_list`, which answers
  only somebody allowed to *read* `POS Opening Entry`. A cashier is not, and
  should not be: the first real cashier to take a payment was refused with a
  bare `PermissionError`. The fact is the same; it is asked without the reader.
* **Is there stock?** ERPNext adds up every POS invoice the warehouse has ever
  had and throws away the posted ones — 28 seconds over 200,000 of them on the
  rehearsal site, against 87 ms for today's alone — and it does the sum even
  for an item that may go negative (`docs/14` §5.5, §12.1). Stage 3 puts our
  own check here; until then a sale is not held up by the stock ledger.

A profile that is not one of our tills gets ERPNext's behaviour, untouched:
a restaurant may run ERPNext's own point of sale on another profile.

`override_doctype_class`, not a patch to ERPNext (`CLAUDE.md` §3). Checked
before choosing it: the ZATCA app reaches `POS Invoice` through `doc_events`,
and neither ERPNext nor HRMS overrides this class.
"""

import frappe
from erpnext.accounts.doctype.pos_invoice.pos_invoice import POSInvoice
from frappe import _

from restaurant_pos.utils.order import branch_of_profile


class RPOSInvoice(POSInvoice):
	def is_a_till_sale(self) -> bool:
		"""One of our terminals — a profile with a restaurant section, hence a branch."""
		return bool(branch_of_profile(self.pos_profile))

	def validate_pos_opening_entry(self):
		if not self.is_a_till_sale():
			return super().validate_pos_opening_entry()

		if not frappe.db.exists(
			"POS Opening Entry", {"pos_profile": self.pos_profile, "status": "Open", "docstatus": 1}
		):
			frappe.throw(
				_("No open POS Opening Entry found for POS Profile {0}.").format(
					frappe.bold(self.pos_profile)
				),
				title=_("POS Opening Entry Missing"),
			)

	def validate_stock_availablility(self):
		if not self.is_a_till_sale():
			return super().validate_stock_availablility()


def keep_sales_out_of_the_closing(doc, method=None) -> None:
	"""`POS Closing Entry.validate` — a drawer of ours closes without its invoices.

	Our drawer **is** ERPNext's `POS Opening Entry`, and counting it makes a `POS
	Closing Entry` — with an empty invoice list, on purpose (`D-022`). ERPNext
	consolidates whatever is on that list into Sales Invoices when the entry is
	submitted, and our own posting does that job (`D-308`): a closing made by
	hand at the desk, which fills the list by itself, would post every sale of
	the drawer a second time.
	"""
	if doc.get("pos_transactions") and branch_of_profile(doc.pos_profile):
		frappe.throw(
			_(
				"Close this drawer from the till. A closing entry that lists its invoices would post "
				"them twice: Restaurant POS posts a terminal's sales itself."
			),
			title=_("Not From Here"),
		)

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""One branch's till sales for one date, posted together (`D-313`).

A till sale is a `POS Invoice` and reaches neither the accounts nor the stock
ledger when it is rung up (`D-308`). This is the unit that takes it there: the
invoices of one branch and one calendar date, claimed, then posted as one sales
entry, one returns entry and one stock issue.

**Written by `utils/posting` and nobody else.** Every field is read-only: the
batch is the record of what was posted and what failed, and a record somebody
can adjust says nothing about either.
"""

from frappe.model.document import Document


class POSPostingBatch(Document):
	pass

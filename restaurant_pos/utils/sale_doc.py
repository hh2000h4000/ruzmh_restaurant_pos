# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The document a till sale is — named once (`D-311`).

Seventy places said `"Sales Invoice"` and meant *the bill the till just sold*.
That document is about to become a `POS Invoice` (`D-308`), and seventy edits
are seventy chances to miss one: a report that still reads the old table shows
an empty day and raises nothing.

So the name lives here, and everything that means "the till's sale" reads it.
What stays spelled out elsewhere is what really is a Sales Invoice whatever the
till does: the VAT return's sales side, the stock ledger's voucher types, the
ZATCA app's own tables.

No imports, on purpose: `hooks.py` and the installer read this too.
"""

#: What one sale at the till is saved as.
SALE = "Sales Invoice"

#: A line of it. (Its payments and taxes are `Sales Invoice Payment` and
#: `Sales Taxes and Charges` on either document — told apart by `parenttype`.)
SALE_ITEM = "Sales Invoice Item"

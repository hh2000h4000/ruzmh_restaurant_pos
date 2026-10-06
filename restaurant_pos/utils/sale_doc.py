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
SALE = "POS Invoice"

#: A line of it. (Its payments and taxes are `Sales Invoice Payment` and
#: `Sales Taxes and Charges` on either document — told apart by `parenttype`.)
SALE_ITEM = "POS Invoice Item"

#: On a line: what one unit of it cost, written by the posting that took it from
#: the warehouse (`D-314`). A recipe's rows carry theirs in ERPNext's own
#: `Packed Item.incoming_rate`. Empty until the sale's day is posted.
LINE_COST = "rpos_cost_rate"

#: On a credit note's line: it came back and was thrown away (`D-315`). Its
#: stock does not return to the shelf, and its cost is waste, not cost of sales.
WASTED = "rpos_wasted"

#: What a day of till sales is posted to the accounts as (`D-313`): ERPNext's own
#: consolidated Sales Invoice. Not the sale — the entry the sales add up to.
POSTED_ENTRY = "Sales Invoice"

#: On a credit note's line: the sold line it takes back. ERPNext counts what has
#: already come back through this field, and so do we.
RETURNED_LINE = "pos_invoice_item"

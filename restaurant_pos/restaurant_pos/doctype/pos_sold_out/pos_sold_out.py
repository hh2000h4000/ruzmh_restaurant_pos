# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Something a branch has run out of today (`D-322`).

**A mark, not a stock movement.** The cook says the soup is finished while the
ledger says there is a pot left; the till believes the cook. A row here takes
the item off sale in its branch until somebody brings it back or the day is
closed — and touches neither the warehouse nor the accounts.

Written by `utils/availability` and nobody else.
"""

from frappe.model.document import Document


class POSSoldOut(Document):
	pass

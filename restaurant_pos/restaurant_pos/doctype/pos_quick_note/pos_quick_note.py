# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class POSQuickNote(Document):
	"""A note a kitchen hears often enough that nobody should retype it.

	"No onion", "extra spicy", "rush this" — typed on a touch screen in Arabic,
	in the middle of a lunch rush, one letter at a time. The list is data so a
	restaurant writes its own; nothing here is hardcoded (FR-2.9).
	"""

	pass

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class RestaurantOrderTable(Document):
	"""One more table this bill occupies (`BR-063`).

	The bill's own ``table`` stays the first one, so every path that already
	reads it keeps working; this holds the ones joined to it.
	"""

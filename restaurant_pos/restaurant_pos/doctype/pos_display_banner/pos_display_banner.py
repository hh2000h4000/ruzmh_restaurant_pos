# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class POSDisplayBanner(Document):
	"""One banner on the screen facing the room (`FR-13.1`, `D-203`).

	A row rather than a field because restaurants run more than one offer, and
	they rotate. The image carries its own words — that is how a restaurant's
	marketing already arrives, designed, from whoever made the poster.
	"""

	pass

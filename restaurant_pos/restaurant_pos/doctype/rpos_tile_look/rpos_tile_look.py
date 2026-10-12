# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class RPOSTileLook(Document):
	"""One tile's own picture and colour (`D-351`).

	Named by the page it is on, what it is, and the label its row carries — not
	by the row itself, because Frappe makes a page's rows anew on every save.
	"""

	pass

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class RPOSTileSettings(Document):
	"""How the desk's tiled pages look (`D-351`).

	The colour and the size are the site's; a tile's own look is a row, written
	from the page it is on (`api/desk.py`). Kept in one record so a page reads
	all of it in the request it already makes.
	"""

	pass

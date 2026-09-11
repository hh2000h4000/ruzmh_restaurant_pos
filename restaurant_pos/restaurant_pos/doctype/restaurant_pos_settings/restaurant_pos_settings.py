# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

#: Pictures the till shows to a cashier, so they must be files anyone signed in may fetch.
PICTURES = ("default_group_image", "default_item_image")


class RestaurantPOSSettings(Document):
	"""The till's settings that belong to no other record (`FR-16.1`, `D-197`).

	A page in the desk, not a screen in the till: the manager already keeps the
	menu, the floor and the terminals there (`FR-16.2`), and so do Foodics,
	Square and Toast — a back office behind the till, not settings on it.

	It starts with the pictures a group or a dish shows when it has none of its
	own; the till reads them in `api/session.py`.
	"""

	def validate(self):
		# A private file is served only to someone allowed to read this page, and
		# a cashier is not: the tile would draw a broken picture on every till.
		for field in PICTURES:
			if (self.get(field) or "").startswith("/private/"):
				frappe.throw(
					_(
						"{0} is a private file, and the till cannot show it to a cashier. Upload it as public."
					).format(_(self.meta.get_label(field)))
				)

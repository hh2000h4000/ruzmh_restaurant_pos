# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from restaurant_pos.utils.files import assert_public

#: The bell's page, at its narrowest and widest (`D-301`): fewer than five is
#: a list that pages on every glance, more than fifty is the flood it pages to avoid.
ALERTS_PER_PAGE = (5, 50)

#: Pictures the till shows to a cashier, so they must be files anyone signed in may fetch.
PICTURES = ("default_group_image", "default_item_image")


class RestaurantPOSSettings(Document):
	"""The till's settings that belong to no other record (`FR-16.1`, `D-197`).

	A page in the desk, not a screen in the till: the manager already keeps the
	menu, the floor and the terminals there (`FR-16.2`), and so do Foodics,
	Square and Toast — a back office behind the till, not settings on it.

	It holds the pictures a group or a dish shows when it has none of its own,
	and what the screen facing the room shows: a sentence and the banners
	(`D-202`, `D-203`). The till reads all of it in `api/session.py`.
	"""

	def validate(self):
		assert_public(self, PICTURES)
		# A banner is shown to a guest, so a private file would leave the room
		# looking at a broken picture — the same rule, on every row.
		for banner in self.banners:
			assert_public(banner, ("image",))

		# Empty on a site that had these settings before the field existed.
		self.alerts_per_page = self.alerts_per_page or 20
		low, high = ALERTS_PER_PAGE
		if not low <= self.alerts_per_page <= high:
			frappe.throw(_("Alerts per page must be between {0} and {1}.").format(low, high))

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from restaurant_pos.utils import theme as theme_service
from restaurant_pos.utils.files import assert_public


class RPOSTheme(Document):
	"""A restaurant's brand colours and logo for the till (`FR-15.1`, `D-198`).

	Edited on its desk form, as the rest of the configuration is (`D-197`): the
	colour picker, the preview of the record and the permissions are Frappe's
	own, and the till applies the theme on its next load.

	Two rules are enforced here rather than left to the person choosing:

	* **Readable** — every foreground/background pair clears 4.5:1. A cashier
	  reads this screen under restaurant lighting, in a hurry, and a pretty
	  theme nobody can read costs orders (`FR-15.3`, `06` §Accessibility).
	* **One default** — marking this one the default takes the mark off the
	  others, so `FR-15.2`'s last step can never find two answers.
	"""

	def validate(self):
		assert_public(self, ("brand_logo",))
		self._readable()

	def _readable(self) -> None:
		for background, foreground in theme_service.PAIRS:
			back, fore = theme_service.FIELDS[background], theme_service.FIELDS[foreground]
			ratio = theme_service.contrast(self.get(back), self.get(fore))
			if ratio < theme_service.MINIMUM_CONTRAST:
				frappe.throw(
					_(
						"{0} on {1} is {2}:1. A cashier needs {3}:1 to read it under restaurant lighting."
					).format(
						_(self.meta.get_label(fore)),
						_(self.meta.get_label(back)),
						f"{ratio:.1f}",
						f"{theme_service.MINIMUM_CONTRAST:g}",
					)
				)

	def on_update(self) -> None:
		if not self.is_default:
			return

		for other in frappe.get_all(
			"RPOS Theme", filters={"is_default": 1, "name": ("!=", self.name)}, pluck="name"
		):
			frappe.db.set_value("RPOS Theme", other, "is_default", 0)

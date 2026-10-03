# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from restaurant_pos.utils import announcements


class POSAnnouncement(Document):
	"""A message from the office to the people at the tills (`D-303`).

	**Submitting is sending.** The people it reaches are fixed at that moment —
	a cashier hired next week does not find last month's notices — and the form
	then shows who has read it. Cancelling takes it out of every bell.

	**Two bells, one record.** A cashier reads it in the till's bell; someone
	who works in the desk finds it in ERPNext's own bell too, as a Frappe
	`Notification Log` — and opening it there counts as reading it here.
	"""

	def before_submit(self):
		announcements.address(self)

	def on_submit(self):
		announcements.notify_office(self)

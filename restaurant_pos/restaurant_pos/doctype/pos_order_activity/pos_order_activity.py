# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class POSOrderActivity(Document):
	"""One thing that happened to a bill.

	No validation and no logic: entries are written by `utils/activity.log` at
	the moment the action happens, and a history that could be edited afterwards
	would not be a history.
	"""

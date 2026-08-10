# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class POSSyncEntry(Document):
	"""Ledger of processed offline-queue actions.

	Written only by ``utils/idempotency.py``. See ``DECISIONS.md`` D-019.
	"""

	pass

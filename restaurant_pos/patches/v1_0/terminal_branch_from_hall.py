# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Give every terminal its hall's branch, and stop if any disagree (`D-391`).

Runs before `after_migrate` makes the custom fields, so it makes the one it
writes first.
"""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from restaurant_pos.setup.install import CUSTOM_FIELDS
from restaurant_pos.utils import terminal_branch


def execute():
	field = [row for row in CUSTOM_FIELDS["POS Profile"] if row["fieldname"] == terminal_branch.FIELD]
	create_custom_fields({"POS Profile": field}, ignore_validate=True)
	terminal_branch.fill_from_halls()

"""A device's print agent, from the cable receipt printer it already uses (`D-402`).

The check on save asks every device with a cable receipt printer to name its
agent. Devices set up before it would be refused at their next save, so each
takes the agent its receipt printer already prints through — what it does
today, written down.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	from restaurant_pos.setup.install import CUSTOM_FIELDS
	from restaurant_pos.utils.terminal_printing import CABLED

	create_custom_fields({"POS Profile": CUSTOM_FIELDS["POS Profile"]}, ignore_validate=True)

	for row in frappe.get_all(
		"POS Profile",
		filters={"default_printer": ("is", "set"), "rpos_print_agent": ("is", "not set")},
		fields=["name", "default_printer"],
	):
		kind, agent = frappe.db.get_value(
			"POS Printer", row.default_printer, ["connection_type", "print_agent"]
		)
		if kind in CABLED and agent:
			frappe.db.set_value("POS Profile", row.name, "rpos_print_agent", agent, update_modified=False)

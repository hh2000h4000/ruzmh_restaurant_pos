# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Install-time setup for the Restaurant POS app.

Phase 1 responsibility: extend the ERPNext masters listed in
``docs/05_Database_Design.md`` section 18 with the fields RPOS needs.

Per ``docs/04_System_Architecture.md`` section 9, ERPNext core is never
modified - every extension is a ``Custom Field``.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from restaurant_pos.setup.defaults import create_default_data

# ``Restaurant Branch`` in the database design is the ERPNext ``Branch`` DocType
# extended with restaurant configuration (see 10_Implementation_Plan.md, Phase 1).
CUSTOM_FIELDS = {
	"Branch": [
		{
			"fieldname": "rpos_settings_section",
			"fieldtype": "Section Break",
			"label": "Restaurant Settings",
			"insert_after": "branch",
		},
		{
			"fieldname": "company",
			"fieldtype": "Link",
			"options": "Company",
			"label": "Company",
			"reqd": 1,
			"insert_after": "rpos_settings_section",
		},
		{
			"fieldname": "manager",
			"fieldtype": "Link",
			"options": "User",
			"label": "Manager",
			"insert_after": "company",
		},
		{
			"fieldname": "phone",
			"fieldtype": "Data",
			"options": "Phone",
			"label": "Phone",
			"insert_after": "manager",
		},
		{
			"fieldname": "vat_number",
			"fieldtype": "Data",
			"label": "VAT Number",
			"description": "Printed on customer receipts.",
			"insert_after": "phone",
		},
		{
			"fieldname": "rpos_settings_cb",
			"fieldtype": "Column Break",
			"insert_after": "vat_number",
		},
		{
			"fieldname": "default_warehouse",
			"fieldtype": "Link",
			"options": "Warehouse",
			"label": "Default Warehouse",
			"description": "Stock is deducted from this warehouse.",
			"reqd": 1,
			"insert_after": "rpos_settings_cb",
		},
		{
			"fieldname": "default_cost_center",
			"fieldtype": "Link",
			"options": "Cost Center",
			"label": "Default Cost Center",
			"reqd": 1,
			"insert_after": "default_warehouse",
		},
		{
			"fieldname": "shift_type",
			"fieldtype": "Select",
			"options": "single\nmulti",
			"default": "single",
			"label": "Shift Type",
			"reqd": 1,
			"insert_after": "default_cost_center",
		},
		{
			"fieldname": "settlement_required",
			"fieldtype": "Check",
			"label": "Settlement Required",
			"insert_after": "shift_type",
		},
		{
			"fieldname": "is_active",
			"fieldtype": "Check",
			"label": "Is Active",
			"default": "1",
			"insert_after": "settlement_required",
		},
		{
			"fieldname": "rpos_address_section",
			"fieldtype": "Section Break",
			"label": "Address",
			"insert_after": "is_active",
		},
		{
			"fieldname": "branch_address",
			"fieldtype": "Text",
			"label": "Branch Address",
			"insert_after": "rpos_address_section",
		},
	],
	"Item": [
		{
			"fieldname": "rpos_section",
			"fieldtype": "Section Break",
			"label": "Restaurant POS",
			"collapsible": 1,
			"insert_after": "item_group",
		},
		{
			"fieldname": "pos_display_name_ar",
			"fieldtype": "Data",
			"label": "POS Display Name (Arabic)",
			"translatable": 1,
			"insert_after": "rpos_section",
		},
		{
			"fieldname": "rpos_section_cb",
			"fieldtype": "Column Break",
			"insert_after": "pos_display_name_ar",
		},
		{
			"fieldname": "default_production_center",
			"fieldtype": "Link",
			"options": "Production Center",
			"label": "Default Production Center",
			"description": "Kitchen routing priority level 5.",
			"insert_after": "rpos_section_cb",
		},
		{
			"fieldname": "rpos_modifier_section",
			"fieldtype": "Section Break",
			"label": "POS Modifier Groups",
			"collapsible": 1,
			"insert_after": "default_production_center",
		},
		{
			"fieldname": "pos_modifier_groups",
			"fieldtype": "Table",
			"options": "Modifier Group Assignment",
			"label": "Modifier Groups",
			"description": "Row order determines display order in the modifier popup.",
			"insert_after": "rpos_modifier_section",
		},
	],
	# The manager PIN belongs to a person, not a role (DECISIONS.md D-016).
	# Its value never reaches this column: restaurant_pos.utils.manager_pin
	# strips it on validate and stores a one-way hash instead (D-015).
	"User": [
		{
			"fieldname": "rpos_section",
			"fieldtype": "Section Break",
			"label": "Restaurant POS",
			"collapsible": 1,
			"insert_after": "role_profile_name",
		},
		{
			"fieldname": "pos_manager_pin",
			"fieldtype": "Password",
			"label": "POS Manager PIN",
			"description": "4 digits, used to approve overrides. Write-only — never displayed.",
			"no_copy": 1,
			"insert_after": "rpos_section",
		},
	],
	"Item Group": [
		{
			"fieldname": "rpos_section",
			"fieldtype": "Section Break",
			"label": "Restaurant POS",
			"collapsible": 1,
			"insert_after": "is_group",
		},
		{
			"fieldname": "default_production_center",
			"fieldtype": "Link",
			"options": "Production Center",
			"label": "Default Production Center",
			"description": "Kitchen routing priority level 6.",
			"insert_after": "rpos_section",
		},
	],
	"POS Profile": [
		{
			"fieldname": "rpos_section",
			"fieldtype": "Section Break",
			"label": "Restaurant POS",
			"insert_after": "company",
		},
		{
			"fieldname": "restaurant_section",
			"fieldtype": "Link",
			"options": "Restaurant Section",
			"label": "Restaurant Section",
			"insert_after": "rpos_section",
		},
		{
			"fieldname": "screen_layout",
			"fieldtype": "Link",
			"options": "POS Screen Layout",
			"label": "Screen Layout",
			"insert_after": "restaurant_section",
		},
		{
			"fieldname": "rpos_section_cb",
			"fieldtype": "Column Break",
			"insert_after": "screen_layout",
		},
		{
			"fieldname": "default_printer",
			"fieldtype": "Link",
			"options": "POS Printer",
			"label": "Default Printer",
			"description": "Cashier printer, and the final fallback for kitchen routing.",
			"insert_after": "rpos_section_cb",
		},
		{
			"fieldname": "restaurant_shift",
			"fieldtype": "Link",
			"options": "Restaurant Shift",
			"label": "Current Restaurant Shift",
			"no_copy": 1,
			"insert_after": "default_printer",
		},
		{
			"fieldname": "rpos_order_types_section",
			"fieldtype": "Section Break",
			"label": "Allowed Order Types",
			"insert_after": "restaurant_shift",
		},
		{
			"fieldname": "allowed_order_types",
			"fieldtype": "Table",
			"options": "POS Profile Order Type",
			"label": "Allowed Order Types",
			"description": "Leave empty to show every active order type on this terminal.",
			"insert_after": "rpos_order_types_section",
		},
	],
}

# Phase 3 adds three more POS Profile fields (customer_receipt_template,
# kot_template, shift_report_template) once the POS Print Template DocType exists.


#: Roles that settle an order and therefore create a Sales Invoice.
INVOICING_ROLES = (
	"POS Cashier",
	"POS Senior Cashier",
	"POS Manager",
	"Restaurant Manager",
	"Restaurant Admin",
)


#: What a POS role needs on ERPNext's own DocTypes, and nothing more.
#:
#: `08_Security.md` §2 already specifies "Read: Item, Customer" for a cashier;
#: it was never granted, so the first non-Administrator to take a payment hit
#: ERPNext's own permission checks. Those checks call
#: ``frappe.has_permission()`` directly and ignore the document-level
#: ``ignore_permissions`` our code passes, so a role permission is the only
#: thing that satisfies them.
#:
#: ``Account`` gets ``select`` rather than ``read``: enough to be attached to an
#: invoice, not enough to open the chart of accounts or read a balance.
#: ERPNext's own answer here is the broad ``Accounts User`` role, which would
#: hand a cashier the whole accounting module.
ERPNEXT_PERMISSIONS = {
	"Item": {"read": 1},
	"Customer": {"read": 1},
	"Account": {"select": 1},
}


def grant_erpnext_permissions() -> None:
	"""Give the POS roles the ERPNext rights their work requires.

	Idempotent: a DocType a role already has a Custom DocPerm for is left alone,
	so an administrator who tightened or widened something keeps their change.
	"""
	from frappe.permissions import add_permission, update_permission_property

	for doctype, rights in ERPNEXT_PERMISSIONS.items():
		if not frappe.db.exists("DocType", doctype):
			continue

		for role in INVOICING_ROLES:
			if not frappe.db.exists("Role", role):
				continue

			if frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role}):
				continue

			add_permission(doctype, role, 0)
			for ptype, value in rights.items():
				update_permission_property(doctype, role, 0, ptype, value)

			# add_permission() grants read by default; drop it where the map
			# asks for something narrower.
			if "read" not in rights:
				update_permission_property(doctype, role, 0, "read", 0)


def after_install():
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
	grant_erpnext_permissions()
	frappe.db.commit()

	# Shipped defaults run on install only. See setup/defaults.py for why they
	# must never be re-applied on migrate.
	create_default_data()


def after_migrate():
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
	grant_erpnext_permissions()

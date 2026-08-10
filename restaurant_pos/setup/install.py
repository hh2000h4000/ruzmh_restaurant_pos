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


def after_install():
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
	frappe.db.commit()


def after_migrate():
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)

// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

// Which dishes sold, over a stretch of days (`D-243`). The month to date is the
// default because that is the question an owner opens this to ask; a single day
// is already answered by the till's own X report.
frappe.query_reports["Item Sales"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "branch",
			label: __("Branch"),
			fieldtype: "Link",
			options: "Branch",
		},
		{
			fieldname: "order_type",
			label: __("Order Type"),
			fieldtype: "Link",
			options: "Restaurant Order Type",
		},
		{
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
		},
		{
			fieldname: "group_by_item_group",
			label: __("One row per group, not per dish"),
			fieldtype: "Check",
		},
		{
			fieldname: "show_cost",
			label: __("Show cost and profit"),
			fieldtype: "Check",
		},
	],
};

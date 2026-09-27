// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

// Every bill of the period — one line a bill, or one line an item (`D-273`).
frappe.query_reports["Invoice Sales"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
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
			// `D-279` — which of the branch's tills rang it up.
			fieldname: "pos_profile",
			label: __("Cashier Device"),
			fieldtype: "Link",
			options: "POS Profile",
		},
		{
			fieldname: "order_type",
			label: __("Order Type"),
			fieldtype: "Link",
			options: "Restaurant Order Type",
		},
		{
			fieldname: "view",
			label: __("Show"),
			fieldtype: "Select",
			options: [
				{ value: "invoice", label: __("One line per invoice") },
				{ value: "item", label: __("One line per item") },
			],
			default: "invoice",
		},
		{
			fieldname: "discounted_only",
			label: __("Discounted bills only"),
			fieldtype: "Check",
			default: 0,
		},
	],
};

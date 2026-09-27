// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

// How the money came in over a period (`D-247`) — cash against card against the
// apps, which is what decides how often somebody walks to the bank.
frappe.query_reports["Payment Types"] = {
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
	],
};

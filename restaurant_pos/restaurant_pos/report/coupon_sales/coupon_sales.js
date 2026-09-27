// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

// What a campaign brought in (`D-248`). Grouped by campaign, because that is the
// unit a marketing decision is made about — one influencer may hold two hundred
// single-use codes, and two hundred rows answer nothing.
frappe.query_reports["Coupon Sales"] = {
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
			fieldname: "campaign",
			label: __("Campaign"),
			fieldtype: "Data",
		},
		{
			fieldname: "coupon",
			label: __("Coupon"),
			fieldtype: "Link",
			options: "POS Coupon",
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
			fieldname: "group_by_coupon",
			label: __("One row per code, not per campaign"),
			fieldtype: "Check",
		},
	],
};

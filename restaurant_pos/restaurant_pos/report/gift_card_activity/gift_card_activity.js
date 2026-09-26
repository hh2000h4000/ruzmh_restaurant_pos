// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

// What moved on gift cards over a period — sold, topped up, spent, given back.
frappe.query_reports["Gift Card Activity"] = {
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
			fieldname: "entry_type",
			label: __("Movement"),
			fieldtype: "Select",
			options: ["", "issue", "top_up", "redeem", "refund", "void"].map((value) => ({
				value,
				label: value ? __(value, null, "POS Gift Card Entry") : "",
			})),
		},
	],
};

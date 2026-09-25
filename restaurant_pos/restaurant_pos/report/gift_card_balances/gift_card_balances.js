// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

// What the restaurant still owes on gift cards, on a chosen day (`D-259`). The
// accountant takes the last day of the month and compares the total against the
// liability account.
frappe.query_reports["Gift Card Balances"] = {
	filters: [
		{
			fieldname: "on",
			label: __("Balance on"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "branch",
			label: __("Issued Branch"),
			fieldtype: "Link",
			options: "Branch",
		},
		{
			fieldname: "hide_empty",
			label: __("Hide cards with nothing left"),
			fieldtype: "Check",
			default: 1,
		},
	],
};

// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

// The points the restaurant owes on a day (`D-196`). The accountant picks the
// last day of the month, and the share of points they expect to be spent.
frappe.query_reports["Loyalty Points Balance"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "on",
			label: __("Balance on"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "loyalty_program",
			label: __("Loyalty Program"),
			fieldtype: "Link",
			options: "Loyalty Program",
		},
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "expected_redemption",
			label: __("Expected to be spent (%)"),
			fieldtype: "Percent",
			default: 100,
		},
	],
};

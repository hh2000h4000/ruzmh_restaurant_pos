// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

// The figures of ZATCA's VAT return, box by box, for the period filed (`D-273`).
frappe.query_reports["VAT Return"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
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
			default: frappe.datetime.month_end(),
			reqd: 1,
		},
	],
	formatter(value, row, column, data, default_formatter) {
		const shown = default_formatter(value, row, column, data);
		return data && data.bold ? `<b>${shown}</b>` : shown;
	},
};

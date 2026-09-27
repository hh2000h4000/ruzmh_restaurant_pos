// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

// Every drawer that did not count out as expected, and who closed it (`D-273`).
frappe.query_reports["Drawer Variances"] = {
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
			fieldname: "cashier",
			label: __("Cashier"),
			fieldtype: "Link",
			options: "User",
		},
		{
			fieldname: "only_differences",
			label: __("Differences only"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "by_cashier",
			label: __("By cashier"),
			fieldtype: "Check",
			default: 0,
		},
	],
	formatter(value, row, column, data, default_formatter) {
		const shown = default_formatter(value, row, column, data);
		if (column.fieldname === "difference" && data && data.difference < 0) {
			return `<span style="color: var(--red-600)">${shown}</span>`;
		}
		return shown;
	},
};

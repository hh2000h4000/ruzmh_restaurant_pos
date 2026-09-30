// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

// What the kitchen used against what the sales say it should have (`D-287`).
// The period runs from one stock count to the next, as Toast's does.
frappe.query_reports["Actual vs Theoretical Usage"] = {
	filters: [
		{
			fieldname: "warehouse",
			label: __("Warehouse"),
			fieldtype: "Link",
			options: "Warehouse",
			reqd: 1,
		},
		{
			fieldname: "opening_count",
			label: __("Opening Count"),
			fieldtype: "Link",
			options: "Stock Reconciliation",
			reqd: 1,
			get_query: () => ({ filters: { docstatus: 1 } }),
		},
		{
			fieldname: "closing_count",
			label: __("Closing Count"),
			fieldtype: "Link",
			options: "Stock Reconciliation",
			get_query: () => ({ filters: { docstatus: 1 } }),
		},
		{
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
		},
	],
};

// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

// When in the day the money comes in (`D-244`). Today by default, because a rota
// is read against a day that is still fresh; widen it to average a fortnight.
frappe.query_reports["Hourly Sales"] = {
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
			fieldname: "slot_minutes",
			label: __("Slot"),
			fieldtype: "Select",
			options: [
				{ value: 60, label: __("Every hour") },
				{ value: 30, label: __("Every half hour") },
				{ value: 15, label: __("Every quarter hour") },
			],
			default: 60,
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

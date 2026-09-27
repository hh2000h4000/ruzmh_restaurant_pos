// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

// Every discount, void and refund in a period, and who allowed it (`D-247`).
// Toast calls this the sales exceptions report; the month to date is the window
// an owner reviews it over.
frappe.query_reports["Sales Exceptions"] = {
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
			fieldname: "action_type",
			label: __("Action Type"),
			fieldtype: "Select",
			options: [
				{ value: "", label: __("Everything") },
				{ value: "discount_applied", label: __("discount_applied") },
				{ value: "void_item", label: __("void_item") },
				{ value: "void_order", label: __("void_order") },
				{ value: "cancel_order", label: __("cancel_order") },
				{ value: "return_created", label: __("return_created") },
				{ value: "price_change", label: __("price_change") },
				{ value: "cash_out", label: __("cash_out") },
			],
		},
		{
			fieldname: "cashier",
			label: __("Cashier"),
			fieldtype: "Link",
			options: "User",
		},
		{
			fieldname: "group_by_staff",
			label: __("One row per person, not per act"),
			fieldtype: "Check",
		},
	],
};

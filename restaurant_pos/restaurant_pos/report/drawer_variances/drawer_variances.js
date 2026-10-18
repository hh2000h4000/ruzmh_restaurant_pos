// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

// Every drawer that did not count out as expected, and who closed it (`D-273`).
// And the accountant books each difference from here (`D-357`).
frappe.provide("restaurant_pos");

restaurant_pos.book_drawer_difference = async function (closing, company) {
	const fallback = await frappe.xcall("restaurant_pos.api.drawer_difference.default_account");
	const dialog = new frappe.ui.Dialog({
		title: __("Book the difference on {0}", [closing]),
		fields: [
			{
				fieldname: "account",
				fieldtype: "Link",
				options: "Account",
				label: __("Account"),
				reqd: 1,
				default: fallback,
				description: __(
					"The shortage account writes it off. To charge the cashier, choose a receivable account — their employee record is the party.",
				),
				get_query: () => ({ filters: { company, is_group: 0 } }),
			},
		],
		primary_action_label: __("Book"),
		primary_action: async ({ account }) => {
			const { journal_entry } = await frappe.xcall("restaurant_pos.api.drawer_difference.book", {
				closing_entry: closing,
				account,
			});
			dialog.hide();
			frappe.show_alert({ message: __("Booked in {0}", [journal_entry]), indicator: "green" });
			frappe.query_report.refresh();
		},
	});
	dialog.show();
};

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
		// A difference nobody has booked yet: the way to book it, on its own row.
		if (column.fieldname === "entry" && data && data.closing && !data.entry && Math.abs(data.difference) >= 0.01) {
			const closing = frappe.utils.escape_html(data.closing);
			const company = frappe.utils.escape_html(data.company || "");
			return `<button class="btn btn-xs btn-default" onclick="restaurant_pos.book_drawer_difference('${closing}', '${company}')">${__("Book")}</button>`;
		}
		return shown;
	},
};

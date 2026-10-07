// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

// Which dishes sold, over a stretch of days (`D-243`). The month to date is the
// default because that is the question an owner opens this to ask; a single day
// is already answered by the till's own X report.
frappe.query_reports["Item Sales"] = {
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
			fieldname: "order_type",
			label: __("Order Type"),
			fieldtype: "Link",
			options: "Restaurant Order Type",
		},
		{
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
		},
		{
			fieldname: "group_by_item_group",
			label: __("One row per group, not per dish"),
			fieldtype: "Check",
		},
		{
			fieldname: "show_cost",
			label: __("Show cost and profit"),
			fieldtype: "Check",
		},
		{
			// `D-286` — how many meals sold and what they brought in, instead of
			// the burgers and drinks they were made of.
			fieldname: "combos_as_meals",
			label: __("Combos as meals"),
			fieldtype: "Check",
		},
	],

	/**
	 * The total of a ratio is the ratio of the totals (`D-332`).
	 *
	 * Frappe's total row adds a column up, which for "Food Cost %" and
	 * "Margin %" adds percentages: the owner's report read 516.68 under food
	 * cost. The table works its totals out in the browser, over the rows on
	 * screen, so the right figure is worked out there too — cost over sales,
	 * profit over sales — and follows a filter typed into a column.
	 */
	get_datatable_options(options) {
		const RATIOS = { cost_ratio: "cost", margin: "profit" };
		const standard = options.hooks && options.hooks.columnTotal;

		options.hooks = Object.assign({}, options.hooks, {
			columnTotal(values, cell) {
				const over = RATIOS[cell.column.id];
				if (!over) return standard ? standard.call(this, values, cell) : null;

				const at = (id) => this.datamanager.getColumns().findIndex((column) => column.id === id);
				const sum = (id) =>
					this.bodyRenderer.visibleRows.reduce((total, row) => total + flt(row[at(id)].content), 0);
				const sales = sum("amount");
				return sales ? (sum(over) / sales) * 100 : 0;
			},
		});
		return options;
	},
};

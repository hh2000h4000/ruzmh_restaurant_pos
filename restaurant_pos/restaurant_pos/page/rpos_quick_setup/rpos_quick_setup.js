// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

// D-307 — from an installed app to a till that can sell, in one form: the
// branch, its halls and tables, and a terminal, made on the company's own
// warehouse and accounts. The pairing code comes back at the end, because the
// next thing anybody does is pair the till.
frappe.pages["rpos-quick-setup"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Quick Setup"),
		single_column: true,
	});

	$(`<p class="text-muted" style="max-width:640px">${__(
		"A few answers, and the branch, its sections and tables, and a cashier terminal are made for you. You can change any of them later from their own pages.",
	)}</p>`).appendTo(page.main);

	const form = new frappe.ui.FieldGroup({
		parent: $("<div>").appendTo(page.main),
		fields: [
			{
				fieldname: "company",
				fieldtype: "Link",
				options: "Company",
				label: __("Company"),
				reqd: 1,
				default: frappe.defaults.get_user_default("Company"),
			},
			{
				fieldname: "branch",
				fieldtype: "Data",
				label: __("Branch Name"),
				reqd: 1,
				description: __("As your staff call it, for example Olaya Branch."),
			},
			{ fieldtype: "Section Break", label: __("What does the branch have?") },
			{ fieldname: "dine_in", fieldtype: "Check", label: __("Dining Hall"), default: 1 },
			{
				fieldname: "tables",
				fieldtype: "Int",
				label: __("Number of Tables"),
				default: 10,
				depends_on: "dine_in",
			},
			{ fieldtype: "Column Break" },
			{ fieldname: "takeaway", fieldtype: "Check", label: __("Takeaway"), default: 1 },
			{ fieldname: "delivery", fieldtype: "Check", label: __("Delivery"), default: 0 },
			{ fieldtype: "Section Break", label: __("Cashier Terminal") },
			{
				fieldname: "terminal",
				fieldtype: "Data",
				label: __("Terminal Name"),
				reqd: 1,
				default: __("Cashier 1"),
			},
			{
				fieldname: "price_list",
				fieldtype: "Link",
				options: "Price List",
				label: __("Menu Price List"),
				get_query: () => ({ filters: { selling: 1, enabled: 1 } }),
				description: __("Empty takes the first selling price list."),
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "taxes_and_charges",
				fieldtype: "Link",
				options: "Sales Taxes and Charges Template",
				label: __("VAT Template"),
				get_query: () => ({ filters: { company: form.get_value("company") } }),
				description: __("Empty takes the company's default template."),
			},
		],
	});
	form.make();

	const result = $("<div style='margin-top:24px'>").appendTo(page.main);

	page.set_primary_action(__("Create"), () => {
		const values = form.get_values();
		if (!values) return;

		frappe.call({
			method: "restaurant_pos.api.quick_setup.run",
			args: { values },
			type: "POST",
			freeze: true,
			freeze_message: __("Setting up the branch…"),
			callback: ({ message }) => {
				if (!message) return;
				show_result(result, message);
				page.set_primary_action(__("Set Up Another Branch"), () => window.location.reload());
			},
		});
	});
};

function show_result($area, made) {
	const link = (doctype, name) =>
		`<a href="/app/${frappe.router.slug(doctype)}/${encodeURIComponent(name)}">${frappe.utils.escape_html(name)}</a>`;
	$area.html(`
		<div class="alert alert-success">
			<p><b>${__("Done.")}</b> ${__("Branch")}: ${link("Branch", made.branch)} · ${__("Terminal")}: ${link("POS Profile", made.pos_profile)}${
				made.tables ? ` · ${__("{0} tables", [made.tables])}` : ""
			}</p>
			<p style="margin-bottom:4px">${__("On the till, open the cashier screen and enter this pairing code:")}</p>
			<p style="font-size:32px;font-weight:600;letter-spacing:4px;font-family:monospace;direction:ltr">${frappe.utils.escape_html(made.pairing_code)}</p>
			<p class="text-muted">${__("It works once, for {0} minutes. A new one can be issued from the terminal's page.", [made.minutes])}</p>
			${
				made.negative_stock_allowed
					? `<p class="text-muted">${__("Stock may now go below zero (Stock Settings), so a day's sales are posted even when a delivery was entered late.")}</p>`
					: ""
			}
			<p>${__("Next: add your menu items and prices, then your staff and their PINs.")} <a href="/rpos-guide">${__("Open the guide")}</a></p>
		</div>
	`);
}

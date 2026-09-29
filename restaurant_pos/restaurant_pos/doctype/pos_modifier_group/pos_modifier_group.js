// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

// The options table shows a Select's stored value, and Frappe translates a
// table cell with no context — so "none" and "sell" read in English, and a
// context-free translation would rename the same words on every other screen
// (`D-174`). The cell reads the option's own words instead (`D-284`).
const OPTION = "POS Modifier Option";

frappe.ui.form.on("POS Modifier Group", {
	onload(frm) {
		for (const fieldname of ["price_effect", "item_effect"]) {
			const df = frm.fields_dict.modifier_options.grid.get_docfield(fieldname);
			df.formatter = (value) => frappe.utils.escape_html(value ? __(value, null, OPTION) : "");
		}
	},
});

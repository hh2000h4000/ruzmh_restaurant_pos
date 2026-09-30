// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

// A table cell shows a Select's stored value translated with no context, so
// "item_price" read in English in the combo table (`D-284`, `D-285`).
frappe.ui.form.on("Item", {
	onload(frm) {
		const grid = frm.fields_dict.rpos_combo_items?.grid;
		if (!grid) return;
		grid.get_docfield("price_source").formatter = (value) =>
			frappe.utils.escape_html(value ? __(value, null, "POS Combo Item") : "");
	},
});

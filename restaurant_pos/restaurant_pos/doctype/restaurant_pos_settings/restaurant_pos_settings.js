// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

// The site's negative-stock setting, read out where the till's stock settings
// are (`D-337`). The sentence is built on the server (`utils/stock_rules`), so
// the two forms that show it cannot word it two ways.
frappe.ui.form.on("Restaurant POS Settings", {
	refresh(frm) {
		const note = (frm.doc.__onload || {}).rpos_stock_note;
		frm.get_field("rpos_stock_note").$wrapper.html(
			note ? `<p class="text-muted small" style="margin-top: var(--margin-sm)">${note}</p>` : "",
		);
	},
});

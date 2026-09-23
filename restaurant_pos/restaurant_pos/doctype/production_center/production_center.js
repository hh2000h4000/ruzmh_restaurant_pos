// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

frappe.ui.form.on("Production Center", {
	refresh(frm) {
		if (frm.is_new()) return;

		// The everyday question — "what does the grill printer print?" — asked
		// once instead of one routing-rule document per item group (D-095).
		frm.add_custom_button(__("What it prints"), () => choose_groups(frm));

		if (!frm.doc.printer) {
			frm.dashboard.set_headline(
				__("No printer on this station. Tickets fall back to the cashier's printer."),
			);
		}
	},
});

function choose_groups(frm) {
	frappe.call({
		method: "restaurant_pos.api.routing.station_groups",
		args: { production_center: frm.doc.name },
		freeze: true,
		callback: ({ message }) => message && show(frm, message),
	});
}

function show(frm, state) {
	const dialog = new frappe.ui.Dialog({
		title: __("What {0} prints", [state.title]),
		fields: [
			{
				fieldtype: "HTML",
				options: `<p class="text-muted">${__(
					"Ticking a group here takes it off whichever station had it. Two stations claiming one group is a coin toss, not a richer setup.",
				)}</p>`,
			},
			{
				fieldtype: "MultiCheck",
				fieldname: "item_groups",
				columns: 2,
				options: state.available.map((group) => ({
					label: label_for(group, state.elsewhere[group]),
					value: group,
					checked: state.assigned.includes(group),
				})),
			},
		],
		primary_action_label: __("Save"),
		primary_action({ item_groups }) {
			frappe.call({
				method: "restaurant_pos.api.routing.set_station_groups",
				args: { production_center: frm.doc.name, item_groups: item_groups || [] },
				freeze: true,
				callback: () => {
					dialog.hide();
					frappe.show_alert({
						message: __("{0} now prints {1} group(s).", [
							state.title,
							(item_groups || []).length,
						]),
						indicator: "green",
					});
				},
			});
		},
	});

	dialog.show();
}

function label_for(group, elsewhere) {
	// Saying where a group goes now is the difference between a list of names
	// and a decision somebody can make: without it, ticking a box silently
	// takes work away from another station.
	return elsewhere
		? `${frappe.utils.escape_html(group)} <span class="text-muted">— ${__("now on {0}", [
				frappe.utils.escape_html(elsewhere),
			])}</span>`
		: frappe.utils.escape_html(group);
}

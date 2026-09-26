// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

/**
 * Cancel a card nobody has spent from (`D-267`).
 *
 * The way a card issued by mistake is undone — a wrong amount, the wrong
 * customer, a company that changed its mind. The server checks everything that
 * decides it (never spent, its drawer still open when sold at a till) and says
 * which one refused; the button only asks why, because the reason goes on the
 * reversing entry an accountant will read.
 */
frappe.ui.form.on("POS Gift Card", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.is_active || !frm.doc.balance) return;

		frm.add_custom_button(__("Cancel issue"), () => {
			frappe.prompt(
				{
					fieldtype: "Small Text",
					fieldname: "reason",
					label: __("Why is it cancelled?"),
					reqd: 1,
				},
				({ reason }) =>
					frappe.call({
						method: "restaurant_pos.api.gift_card.void_card",
						args: { card: frm.doc.name, reason },
						freeze: true,
						callback: () => {
							frappe.show_alert({ message: __("The card is cancelled."), indicator: "green" });
							frm.reload_doc();
						},
					}),
				__("Cancel issue"),
				__("Cancel the card"),
			);
		});
	},
});

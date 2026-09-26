// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

// The gift card method's account is a liability (D-264, D-265). ERPNext's own
// form offers only Bank, Cash and Receivable accounts, so the liability could
// not be chosen at all: the first manager to try created a new account under
// Cash In Hand to have something to pick, and every card spent from it counted
// as cash in the box. With «Gift Card» ticked the list offers liabilities;
// otherwise it is ERPNext's, unchanged.
frappe.ui.form.on("Mode of Payment", {
	setup(frm) {
		frm.set_query("default_account", "accounts", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			const kind = doc.rpos_is_gift_card
				? ["Account", "root_type", "=", "Liability"]
				: ["Account", "account_type", "in", ["Bank", "Cash", "Receivable"]];

			return {
				filters: [kind, ["Account", "is_group", "=", 0], ["Account", "company", "=", row.company]],
			};
		});
	},
});

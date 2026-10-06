// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

/**
 * The list an accountant watches (`D-317`): what failed is red, and a branch
 * whose day is not closed yet can be posted by asking.
 */
frappe.listview_settings["POS Posting Batch"] = {
	get_indicator(doc) {
		const colour = { Posted: "green", Failed: "red", Claimed: "orange" }[doc.status];
		return [__(doc.status), colour, `status,=,${doc.status}`];
	},

	onload(listview) {
		listview.page.add_inner_button(__("Post a branch now"), () => {
			frappe.prompt(
				{ fieldtype: "Link", fieldname: "branch", label: __("Branch"), options: "Branch", reqd: 1 },
				({ branch }) =>
					frappe.call({
						method: "restaurant_pos.api.posting.post_now",
						args: { branch },
						callback: () =>
							frappe.show_alert({
								message: __("Posting {0} has started. This page updates when it is done.", [branch]),
								indicator: "blue",
							}),
					}),
				__("Post a branch now"),
				__("Post now"),
			);
		});
	},
};

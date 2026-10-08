// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

/**
 * "Post now" on a batch that is not finished (`D-317`).
 *
 * A failed batch is run again every hour on its own; this is for the person
 * who has just fixed what stopped it and does not want to wait. The posting
 * runs in the background and the form refreshes itself when it is done.
 */
frappe.ui.form.on("POS Posting Batch", {
	refresh(frm) {
		if (frm.doc.status === "Posted") return;

		frm.add_custom_button(__("Post now"), () =>
			frappe.call({
				method: "restaurant_pos.api.posting.post_now",
				args: { branch: frm.doc.branch },
				callback: () => {
					frappe.show_alert({
						message: __("Posting {0} has started. This page updates when it is done.", [frm.doc.branch]),
						indicator: "blue",
					});
					// **And it does update** (`D-334`): the posting runs in the
					// background, and without a socket the form sat on "Failed"
					// after the batch had been posted. Asked again shortly, and
					// once more for a branch with a long day behind it.
					[5000, 20000].forEach((after) => setTimeout(() => frm.reload_doc(), after));
				},
			}),
		);
	},
});

// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

/**
 * Print the selected cards on A4 (`D-259`).
 *
 * The same sheet the coupons print on, because it is the same request — cards
 * with a code and a QR, ten to a page, cut along the dashes. Only the two lines
 * under the number differ, and that is a parameter rather than a second screen
 * (`CLAUDE.md` §5.5).
 *
 * **What is printed is the balance, not the face value.** A card reprinted after
 * it has been part spent must say what is on it now.
 */
frappe.listview_settings["POS Gift Card"] = {
	onload(listview) {
		listview.page.add_actions_menu_item(
			__("Print card sheet"),
			() => {
				const names = listview.get_checked_items(true);
				if (!names.length) return;

				const query = encodeURIComponent(JSON.stringify(names));
				window.open("/rpos-card-sheet?kind=gift&names=" + query, "_blank");
			},
			false
		);
	},
};

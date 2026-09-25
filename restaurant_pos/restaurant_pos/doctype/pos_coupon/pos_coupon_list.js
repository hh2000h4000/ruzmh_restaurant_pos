// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

/**
 * Print the selected coupons as cards on A4 (`D-250`).
 *
 * **Selection is the point, not a shortcut.** A code is single use: print a
 * sheet twice and two guests hold the same card, and the second one is refused
 * at the counter. Printing what the manager has picked — in a list they can
 * filter by campaign and sort by date — is the one shape where they can see
 * what they are about to hand out.
 *
 * Opened as a page rather than fetched as a PDF because the cards carry Arabic
 * campaign names; `www/rpos_card_sheet.py` records why that matters.
 */
frappe.listview_settings["POS Coupon"] = {
	onload(listview) {
		listview.page.add_actions_menu_item(
			__("Print coupon sheet"),
			() => {
				const names = listview.get_checked_items(true);
				if (!names.length) return;

				const query = encodeURIComponent(JSON.stringify(names));
				window.open("/rpos-card-sheet?kind=coupon&names=" + query, "_blank");
			},
			false
		);
	},
};

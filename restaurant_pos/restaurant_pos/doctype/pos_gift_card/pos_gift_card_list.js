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
/**
 * Issue cards the office is handing out (`D-260`).
 *
 * The till sells a card to whoever is standing there and takes their money into
 * the drawer. This is the other half the user asked about: a company orders
 * fifty and pays by transfer, or one card is written off as an apology. No
 * drawer is involved, so the money is booked against the customer's account —
 * or an account named outright when it is already in the bank.
 */
function issue_cards(listview) {
	const dialog = new frappe.ui.Dialog({
		title: __("Issue cards"),
		fields: [
			{ fieldtype: "Int", fieldname: "count", label: __("How many"), default: 1, reqd: 1 },
			{ fieldtype: "Currency", fieldname: "amount", label: __("Amount on each"), reqd: 1 },
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Link",
				fieldname: "customer",
				label: __("Customer"),
				options: "Customer",
				description: __("Who the cards are for. Left as the debit when no account is named."),
			},
			{
				fieldtype: "Link",
				fieldname: "account",
				label: __("Paid Into"),
				options: "Account",
				description: __("The account the money arrived in. Leave empty to put it on the customer's account."),
			},
			{ fieldtype: "Section Break" },
			{
				fieldtype: "Select",
				fieldname: "pattern",
				label: __("Code Pattern"),
				options: [
					{ value: "random", label: __("Random — cannot be guessed") },
					{ value: "sequential", label: __("Numbered — 10001, 10002, 10003") },
				],
				default: "random",
			},
			{
				fieldtype: "Data",
				fieldname: "start",
				label: __("Start At"),
				default: "10001",
				depends_on: "eval:doc.pattern=='sequential'",
				mandatory_depends_on: "eval:doc.pattern=='sequential'",
				description: __("Leading zeros are kept: 0001 gives 0001, 0002, 0003."),
			},
			{
				fieldtype: "Data",
				fieldname: "prefix",
				label: __("Prefix"),
				depends_on: "eval:doc.pattern=='sequential'",
				description: __("Optional, in front of every number. Letters, digits and dashes."),
			},
			{ fieldtype: "Date", fieldname: "expires_on", label: __("Expires On") },
		],
		primary_action_label: __("Issue"),
		primary_action(values) {
			frappe.call({
				method: "restaurant_pos.api.gift_card.issue_from_the_office",
				args: values,
				freeze: true,
				callback: ({ message }) => {
					if (!message) return;
					dialog.hide();
					frappe.show_alert({
						message: __("{0} cards issued.", [message.cards.length]),
						indicator: "green",
					});
					listview.refresh();
				},
			});
		},
	});

	dialog.show();
}

frappe.listview_settings["POS Gift Card"] = {
	onload(listview) {
		// Always there, not behind a selection: issuing is how cards come into
		// being from the office, and there is nothing to tick first.
		listview.page.add_inner_button(__("Issue cards"), () => issue_cards(listview));

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

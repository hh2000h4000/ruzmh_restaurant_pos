// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

/**
 * What the item scope means changes with the offer, so the form says which (`D-249`).
 *
 * On a percentage or a fixed amount it is **what the discount comes off**. On
 * *buy X get Y* it is **what is counted and what comes free**. On a free item it
 * is **the qualifying purchase only** — the reward is chosen separately below.
 *
 * The user could not find *"buy a grill, get any drink free"* and asked whether
 * it existed. It did, and had a test; what was missing was any word on the
 * screen saying that the scope is the condition rather than the reward. A field
 * whose meaning shifts under you and never says so is a feature nobody can
 * reach.
 */
const SCOPE_MEANS = {
	percentage: "The lines the discount comes off.",
	fixed_amount: "The lines the discount is spread across.",
	buy_x_get_y: "The lines counted towards the offer — and the free ones come from among them.",
	free_item:
		"What the bill must contain to qualify. The free item itself is chosen below: pick Grills here and Drinks below for \"buy a grill, get a drink free\".",
};

function explain_the_scope(frm) {
	const sentence = SCOPE_MEANS[frm.doc.promotion_type];
	frm.get_field("item_scope").set_new_description(sentence ? __(sentence) : "");
}

frappe.ui.form.on("Restaurant Promotion", {
	refresh: explain_the_scope,
	promotion_type: explain_the_scope,

	onload(frm) {
		if (!frm.is_new()) return;

		// **Frappe fills every Time field with the clock when the form opens**
		// (`create_new.py:149`) — unconditional, no default needed, and no way
		// to opt out short of editing core. So a new promotion arrives with
		// `13:38:13` sitting in both hour fields, which reads as a value
		// somebody chose.
		//
		// It is not. A manager who sets only the end time keeps a start of
		// whenever they happened to open the form: open it at nine, set the end
		// to five, and the happy hour silently runs eight hours (`D-170`).
		//
		// Cleared at the source rather than guessed at afterwards. The server
		// cannot tell a stamp from a time somebody meant — `13:38:13` is a legal
		// window start — so no rule there can be both safe and complete. An
		// empty field can: whatever is in it now, a person typed.
		//
		// And it makes the record's own validation mean something again. "Set
		// both Time From and Time To, or neither" could never fire while the
		// stamp filled both; now a half-set window is refused and said out loud.
		frm.set_value("time_from", null);
		frm.set_value("time_to", null);
	},
});

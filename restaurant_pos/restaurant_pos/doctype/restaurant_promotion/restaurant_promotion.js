// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

frappe.ui.form.on("Restaurant Promotion", {
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

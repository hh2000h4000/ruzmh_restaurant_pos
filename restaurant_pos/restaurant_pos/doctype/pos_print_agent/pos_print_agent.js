// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

frappe.ui.form.on("POS Print Agent", {
	refresh(frm) {
		if (frm.is_new()) return;

		// D-212 — the everyday way: a short code typed into the installer.
		frm.add_custom_button(__("Pair a Device"), () => pair_device(frm));
		frm.add_custom_button(__("Generate Keys"), () => generate_keys(frm));

		if (!frm.doc.last_seen) {
			frm.dashboard.set_headline(
				__("This agent has never asked for work. Nothing it owns can print yet."),
			);
			return;
		}

		// Silence is the whole diagnosis. A technician standing at a printer that
		// will not print needs to know whether the agent is alive before they
		// start looking at cables.
		const silent_seconds = (frappe.datetime.now_datetime_as_moment() -
			frappe.datetime.str_to_obj(frm.doc.last_seen)) / 1000;

		if (silent_seconds > 120) {
			frm.dashboard.set_headline(
				__("Silent since {0}. It is not running, or cannot reach this server.", [
					frappe.datetime.prettyDate(frm.doc.last_seen),
				]),
			);
		}
	},
});

function pair_device(frm) {
	frappe.call({
		method: "restaurant_pos.restaurant_pos.doctype.pos_print_agent.pos_print_agent.issue_pairing_code",
		args: { agent: frm.doc.name },
		freeze: true,
		callback: ({ message }) => {
			if (!message) return;
			show_pairing_code(message);
			frm.reload_doc();
		},
	});
}

function show_pairing_code({ code, minutes, url }) {
	// Large and plain: it is read off this screen and typed on another one.
	const dialog = new frappe.ui.Dialog({
		title: __("Pair a Device"),
		fields: [
			{
				fieldtype: "HTML",
				options: `
					<p>${__("On the restaurant's computer, run the print agent installer and enter:")}</p>
					<p class="text-muted" style="margin-bottom:4px">${__("Site address")}</p>
					<p style="font-size:16px;font-family:monospace;direction:ltr">${frappe.utils.escape_html(url)}</p>
					<p class="text-muted" style="margin-bottom:4px">${__("Pairing code")}</p>
					<p style="font-size:32px;font-weight:600;letter-spacing:4px;font-family:monospace;direction:ltr">${frappe.utils.escape_html(code)}</p>
					<p class="text-muted">${__("It works once, for {0} minutes. Asking for a new code cancels this one.", [minutes])}</p>
				`,
			},
		],
		primary_action_label: __("Done"),
		primary_action() {
			dialog.hide();
		},
	});

	dialog.show();
}

function generate_keys(frm) {
	frappe.confirm(
		__(
			"A new secret replaces the old one, and any agent still using the old one stops printing. Continue?",
		),
		() => {
			frappe.call({
				method: "restaurant_pos.restaurant_pos.doctype.pos_print_agent.pos_print_agent.generate_keys",
				args: { agent: frm.doc.name },
				freeze: true,
				callback: ({ message }) => {
					if (!message) return;
					show_keys(message);
					frm.reload_doc();
				},
			});
		},
	);
}

function show_keys(pair) {
	// Shown once, and said so plainly. The server stores the secret encrypted
	// and has no way to read it back, so an administrator who closes this
	// dialog without copying it has to issue another one.
	const [api_key, api_secret] = pair.split(":");

	const dialog = new frappe.ui.Dialog({
		title: __("Agent credentials"),
		fields: [
			{
				fieldtype: "HTML",
				options: `<p>${__(
					"Copy these into the agent's <code>agent.ini</code> now. The secret is not shown again.",
				)}</p>`,
			},
			{ fieldtype: "Data", fieldname: "api_key", label: __("API Key"), read_only: 1, default: api_key },
			{
				fieldtype: "Data",
				fieldname: "api_secret",
				label: __("API Secret"),
				read_only: 1,
				default: api_secret,
			},
		],
		primary_action_label: __("Copy both"),
		primary_action() {
			frappe.utils.copy_to_clipboard(`api_key = ${api_key}\napi_secret = ${api_secret}`);
			dialog.hide();
		},
	});

	dialog.show();
}

// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

frappe.ui.form.on("POS Print Agent", {
	refresh(frm) {
		// An HTML field's content is not passed through translation by the form,
		// so the help is set here where __() reaches it.
		frm.set_df_property(
			"credentials_help",
			"options",
			`<p class="text-muted">${__(
				"Use <b>Pair the Print Agent</b> and type the short code into the agent installer on the restaurant's computer — it works once, for ten minutes. <b>Generate Keys</b> is the manual way: the secret is shown once, to copy into the agent's configuration by hand.",
			)}</p>`,
		);

		if (frm.is_new()) return;

		// D-212 — the everyday way: a short code typed into the installer.
		frm.add_custom_button(__("Pair the Print Agent"), () => pair_device(frm));
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
	// D-402 — pairing another computer takes the agent off this one. Said
	// before it happens: with printers named alike, the old computer's receipts
	// would print at the new one's counter, and nothing would ring.
	if (frm.doc.last_seen) {
		frappe.confirm(
			__(
				"This agent is running on {0} (last seen {1}). Pairing it on another computer stops it there, and that computer's printers stop printing. Continue?",
				[
					frappe.utils.escape_html(frm.doc.host_name || __("another computer")),
					frappe.datetime.prettyDate(frm.doc.last_seen),
				],
			),
			() => issue_code(frm),
		);
		return;
	}
	issue_code(frm);
}

function issue_code(frm) {
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
	// D-402 — named for what it pairs: a till is paired from its own form.
	const dialog = new frappe.ui.Dialog({
		title: __("Pair the Print Agent"),
		fields: [
			{
				fieldtype: "HTML",
				options: `
					<p>${__("On the restaurant's computer, run the print agent installer and enter:")}</p>
					<p class="text-muted" style="margin-bottom:4px">${__("Site address")}</p>
					<p style="font-size:16px;font-family:monospace;direction:ltr">${frappe.utils.escape_html(url)}</p>
					${only_here(url) ? `<p class="text-danger">${__("This address works on this computer only. On the restaurant's computer, type the address it reaches this server by, such as http://192.168.1.10:8000.")}</p>` : ""}
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

// The address is the one this browser opened the desk by. Opened as localhost,
// it names this machine — and from the restaurant's computer, that one. Not
// guessed instead: inside WSL the server's own address is not the one the
// network knows it by, and a wrong address said confidently is worse.
function only_here(url) {
	try {
		const host = new URL(url).hostname;
		return ["localhost", "127.0.0.1", "[::1]", "::1"].includes(host) || host.endsWith(".localhost");
	} catch (e) {
		return false;
	}
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

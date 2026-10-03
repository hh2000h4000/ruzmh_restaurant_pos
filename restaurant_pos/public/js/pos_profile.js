// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

// One terminal, one machine (D-226). The manager issues a short code here and
// the till types it once; freeing the terminal for another machine is this
// form's job too, because it is the manager's decision and nobody else's.
frappe.ui.form.on("POS Profile", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Pair a Till"), () => pair_till(frm));
		// D-301 — heard here, at the volume chosen, before a cashier hears it.
		frm.add_custom_button(__("Test the Alert Sound"), () => play_alert_tone(frm.doc));

		if (!frm.doc.rpos_device_token_hash) {
			frm.dashboard.set_headline(
				__("No till is paired with this terminal yet. Pair one before it can sell."),
			);
			return;
		}

		frm.add_custom_button(__("Unpair the Till"), () => unpair_till(frm));
	},
});

function pair_till(frm) {
	frappe.call({
		method: "restaurant_pos.api.session.issue_device_code",
		args: { pos_profile: frm.doc.name },
		freeze: true,
		callback: ({ message }) => {
			if (!message) return;
			show_pairing_code(message);
			frm.reload_doc();
		},
	});
}

function show_pairing_code({ code, minutes, paired_device }) {
	// Large and plain: it is read off this screen and typed on another one.
	const replacing = paired_device
		? `<p class="text-muted">${__("Using this code moves the terminal off {0}.", [
				frappe.utils.escape_html(paired_device),
			])}</p>`
		: "";

	const dialog = new frappe.ui.Dialog({
		title: __("Pair a Till"),
		fields: [
			{
				fieldtype: "HTML",
				options: `
					<p>${__("On the till, open the cashier screen and enter:")}</p>
					<p class="text-muted" style="margin-bottom:4px">${__("Pairing code")}</p>
					<p style="font-size:32px;font-weight:600;letter-spacing:4px;font-family:monospace;direction:ltr">${frappe.utils.escape_html(code)}</p>
					<p class="text-muted">${__("It works once, for {0} minutes. Asking for a new code cancels this one.", [minutes])}</p>
					${replacing}
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

function unpair_till(frm) {
	frappe.confirm(
		__("{0} stops being able to sell on this terminal until it is paired again. Continue?", [
			frm.doc.rpos_device_name || __("The paired till"),
		]),
		() => {
			frappe.call({
				method: "restaurant_pos.api.session.unpair_device",
				args: { pos_profile: frm.doc.name },
				freeze: true,
				callback: () => frm.reload_doc(),
			});
		},
	);
}

/**
 * The bell's tone, as the till plays it (`D-301`).
 *
 * The notes are data in `alert_tones.json`, read by this and by the till, so a
 * tone sounds the same in both places. The few lines that play them are the
 * one thing written twice: the desk cannot import the till's code.
 */
async function play_alert_tone(doc) {
	const tones = await (await fetch("/assets/restaurant_pos/alert_tones.json")).json();
	const notes = tones[doc.rpos_alert_tone] || tones.chime;
	const volume = Math.min(100, Math.max(1, doc.rpos_alert_volume || 70)) / 100;
	const audio = new (window.AudioContext || window.webkitAudioContext)();
	for (const note of notes) {
		const tone = audio.createOscillator();
		const gain = audio.createGain();
		tone.type = note.wave;
		tone.frequency.value = note.hz;
		tone.connect(gain);
		gain.connect(audio.destination);
		const at = audio.currentTime + note.at;
		gain.gain.setValueAtTime(0.0001, at);
		gain.gain.exponentialRampToValueAtTime(volume, at + 0.02);
		gain.gain.exponentialRampToValueAtTime(0.0001, at + note.for);
		tone.start(at);
		tone.stop(at + note.for + 0.02);
	}
}

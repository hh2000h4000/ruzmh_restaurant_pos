// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

frappe.ui.form.on("POS Printer", {
	refresh(frm) {
		if (frm.is_new()) return;

		// The first question anyone asks a printer setup screen is whether the
		// thing is plugged in. Without this button the first real test is a
		// customer's receipt during service.
		frm.add_custom_button(__("Test Print"), () => test_print(frm));

		if (!frm.doc.print_agent) {
			frm.dashboard.set_headline(
				__("No print agent owns this printer, so nothing can reach it."),
			);
		}
	},
});

function test_print(frm) {
	frappe.call({
		method: "restaurant_pos.api.printing.test_print",
		args: { printer: frm.doc.name },
		freeze: true,
		freeze_message: __("Rendering…"),
		callback: ({ message }) => {
			if (!message) return;
			watch(message.job, frm.doc.title);
		},
	});
}

function failure_in_words(reason, printer) {
	const name = frappe.utils.escape_html(printer || "");
	const words = {
		paper_out: __("{0} is out of paper. Load paper and try again.", [name]),
		paused: __("{0} is paused in Windows. Resume it from its queue in Windows, then try again.", [name]),
		offline: __("Windows sees {0} as offline. Check it is on and its cable is in, then try again.", [name]),
		attention: __("{0} needs attention — a cover open or a paper jam. Check the printer, then try again.", [name]),
		error: __("{0} reports an error. Switch it off and on, then try again.", [name]),
		not_found: __("The agent's computer has no printer by this name. Check the Windows printer name here, exactly as Windows lists it."),
		not_taken: __("{0} did not take the paper within 10 seconds, so it was cancelled to keep it from printing late. Check it is on and connected.", [name]),
		unreachable: __("{0} cannot be reached on the network. Check it is on, and its IP address and port.", [name]),
	};
	return words[reason];
}

function watch(job_name, title) {
	// Queued is not printed. Saying "sent" here and stopping would report
	// success for a printer that is switched off — which is exactly the answer
	// this button exists to rule out.
	const started = Date.now();

	const dialog = new frappe.ui.Dialog({
		title: __("Test print"),
		fields: [{ fieldtype: "HTML", fieldname: "state" }],
	});
	dialog.show();

	const paint = (html) => dialog.fields_dict.state.$wrapper.html(html);
	paint(`<p>${__("Waiting for the agent to take it…")}</p>`);

	const poll = setInterval(() => {
		frappe.db.get_value("POS Print Job", job_name, ["status", "error", "reason"]).then(({ message }) => {
			if (!message) return;

			if (message.status === "printed") {
				clearInterval(poll);
				paint(`<p class="text-success">${__("Printed. Check the paper.")}</p>`);
				return;
			}

			if (message.status === "failed") {
				clearInterval(poll);
				// D-403 — what to do, in words; the agent's own text stays below for
				// the technician. An agent before 1.1.0 sends no reason.
				const said = failure_in_words(message.reason, title);
				paint(
					`<p class="text-danger">${said || __("The agent could not print it.")}</p>
					<p class="text-muted" style="margin-bottom:4px">${__("Details")}</p>
					<pre>${frappe.utils.escape_html(message.error || "")}</pre>`,
				);
				return;
			}

			if (Date.now() - started > 30000) {
				clearInterval(poll);
				paint(
					`<p class="text-warning">${__(
						"Still {0} after 30 seconds. The agent is probably not running — check Last Seen on it.",
						[message.status],
					)}</p>`,
				);
			}
		});
	}, 2000);

	dialog.$wrapper.on("hidden.bs.modal", () => clearInterval(poll));
}

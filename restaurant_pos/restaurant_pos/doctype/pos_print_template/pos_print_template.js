// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

frappe.ui.form.on("POS Print Template", {
	refresh(frm) {
		if (frm.is_new()) return;

		// Designing a receipt blind does not work (D-110). Every layout defect
		// this project has had was written in correct HTML and found by looking
		// at the output.
		frm.add_custom_button(__("Preview"), () => preview(frm));

		explain_which_one_is_used(frm);
	},
});

function preview(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save first — the preview renders what is stored, not what is on screen."));
		return;
	}

	frappe.call({
		method: "restaurant_pos.api.printing.preview_template",
		args: { template: frm.doc.name },
		freeze: true,
		freeze_message: __("Rendering…"),
		callback: ({ message }) => message && show(frm, message),
	});
}

function show(frm, result) {
	const dialog = new frappe.ui.Dialog({
		title: __("{0} — {1} dots wide", [frm.doc.title, result.width_dots]),
		size: "small",
		fields: [
			{
				fieldtype: "HTML",
				options: `
					<p class="text-muted small">${__("Rendered from {0}, exactly as the printer receives it — one bit per dot, no greys.", [
						frappe.utils.escape_html(result.sample || "?"),
					])}</p>
					<div style="background:#fff;border:1px solid #d1d8dd;padding:8px;overflow:auto;max-height:60vh">
						<img src="${result.image}" style="width:100%;image-rendering:pixelated">
					</div>`,
			},
		],
	});

	dialog.show();
}

function explain_which_one_is_used(frm) {
	// The commonest confusion: a template edited carefully that nothing prints,
	// because another one wins the resolution (D-085) — or one that does print,
	// because a terminal chose it on its POS Profile (D-214).
	if (frm.doc.template_type !== "customer_receipt") {
		frm.dashboard.set_headline(by_resolution(frm));
		return;
	}

	frappe.db
		.get_list("POS Profile", { filters: { receipt_template: frm.doc.name }, fields: ["name"] })
		.then((rows) => {
			if (!rows.length) {
				frm.dashboard.set_headline(by_resolution(frm));
				return;
			}

			const chosen = __("Printed by {0}, chosen on the POS Profile.", [
				rows.map((row) => row.name).join(", "),
			]);
			const resolved = frm.doc.branch || frm.doc.is_default ? ` ${by_resolution(frm)}` : "";
			frm.dashboard.set_headline(chosen + resolved);
		});
}

function by_resolution(frm) {
	if (frm.doc.branch) {
		return __("Used for {0} on {1} paper at {2}, ahead of any default.", [
			__(frm.doc.template_type),
			frm.doc.paper_width,
			__("branch {0}", [frm.doc.branch]),
		]);
	}

	return frm.doc.is_default
		? __("The default for {0} on {1} paper. A template naming a branch beats it there.", [
				__(frm.doc.template_type),
				frm.doc.paper_width,
			])
		: __(
				"Nothing prints this: it names no branch and is not the default. Tick Is Default, or set a Branch.",
			);
}

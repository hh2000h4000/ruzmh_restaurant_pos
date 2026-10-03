// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

// D-303 — opened from ERPNext's bell by someone it was sent to: that is reading
// it, so the sender's "who has read it" says so. Asked of the server on every
// open; it marks nothing unless the reader is a recipient who had not read it.
frappe.ui.form.on("POS Announcement", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		const mine = (frm.doc.recipients || []).find(
			(row) => row.user === frappe.session.user && !row.read_at,
		);
		if (!mine) return;

		frappe.call({
			method: "restaurant_pos.api.bell.mark_announcements_read",
			args: { name: frm.doc.name },
			callback: () => frm.reload_doc(),
		});
	},
});

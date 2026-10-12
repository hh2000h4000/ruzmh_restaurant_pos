// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

// One button under the page's name, saying what pressing it will do: the page
// is either shown as tiles or it is not, so there is never a second button.
frappe.ui.form.on("RPOS Tile Settings", {
	refresh: (frm) => draw(frm),
	page: (frm) => draw(frm),
});

async function draw(frm) {
	const wrapper = frm.get_field("page_action").$wrapper.empty();
	const page = frm.doc.page;
	if (!page) return;

	const tiled = await frappe.xcall("restaurant_pos.api.desk.is_tiled", { page });
	// The field may have changed while the answer was on its way.
	if (frm.doc.page !== page) return;

	$(`<button type="button" class="btn btn-primary btn-sm"></button>`)
		.text(tiled ? __("Show it as lists again") : __("Show it as tiles"))
		.appendTo(wrapper.empty())
		.on("click", async () => {
			await frappe.xcall("restaurant_pos.api.desk.tile_page", { page, on: tiled ? 0 : 1 });
			frappe.show_alert({
				message: tiled ? __("The page is lists again.") : __("The page is tiles now. Open it to see."),
				indicator: "green",
			});
			draw(frm);
		});
}

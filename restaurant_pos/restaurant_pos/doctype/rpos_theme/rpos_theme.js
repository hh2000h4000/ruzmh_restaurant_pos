// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

// What the colours will look like, while they are being picked (`FR-15.3`,
// `D-199`). The first person to meet this form picked a colour, was refused
// with a ratio, and could not act on it. The three blocks below are the three
// pairs the server checks, each drawn in the colours themselves and carrying
// its ratio — so the rule is visible before Save, not after.
//
// The text colour shown for an empty field is the one the server will fill in:
// black or white, whichever reads. The arithmetic is WCAG 2.1, the same as
// `utils/theme.py`.

const INK = "#000000";
const PAPER = "#FFFFFF";

function channels(colour) {
	let value = String(colour || "").trim().replace(/^#/, "");
	if (value.length === 3) {
		value = value.split("").map((character) => character + character).join("");
	}
	if (!/^[0-9a-f]{6}$/i.test(value)) return null;

	const number = parseInt(value, 16);
	return [(number >> 16) & 255, (number >> 8) & 255, number & 255];
}

function luminance(colour) {
	const [red, green, blue] = channels(colour).map((value) => {
		const fraction = value / 255;
		return fraction <= 0.03928 ? fraction / 12.92 : ((fraction + 0.055) / 1.055) ** 2.4;
	});
	return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

function contrast(first, second) {
	if (!channels(first) || !channels(second)) return 0;

	const [light, dark] = [luminance(first), luminance(second)].sort((a, b) => b - a);
	return (light + 0.05) / (dark + 0.05);
}

function readableOn(colour) {
	return contrast(colour, INK) >= contrast(colour, PAPER) ? INK : PAPER;
}

function block(base, text, label, chosen) {
	const ratio = contrast(base, text);
	const note = chosen ? __("chosen for you") : __("yours");
	return `
		<div style="flex:1 1 200px;min-width:200px;border-radius:12px;padding:16px;background:${base};color:${text}">
			<div style="font-size:15px;font-weight:600">${frappe.utils.escape_html(label)}</div>
			<div style="font-size:13px;opacity:0.85;margin-top:6px">
				${ratio.toFixed(2)}:1 &middot; ${text} &middot; ${note}
			</div>
		</div>`;
}

function preview(frm) {
	const pairs = [
		["primary_color", "primary_contrast"],
		["secondary_color", "secondary_contrast"],
		["background_color", "text_color"],
	];

	const blocks = pairs
		.map(([baseField, textField]) => {
			const base = frm.doc[baseField];
			if (!channels(base)) return "";

			const chosen = !frm.doc[textField];
			const text = chosen ? readableOn(base) : frm.doc[textField];
			return block(base, text, __(frm.fields_dict[textField].df.label), chosen);
		})
		.join("");

	const surface = channels(frm.doc.surface_color) ? frm.doc.surface_color : PAPER;
	frm.get_field("theme_preview").$wrapper.html(`
		<div style="display:flex;flex-wrap:wrap;gap:12px;padding:16px;border-radius:16px;background:${surface}">
			${blocks}
		</div>`);
}

frappe.ui.form.on("RPOS Theme", {
	refresh: preview,
	primary_color: preview,
	secondary_color: preview,
	background_color: preview,
	surface_color: preview,
	primary_contrast: preview,
	secondary_contrast: preview,
	text_color: preview,
});

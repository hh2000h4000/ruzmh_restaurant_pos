// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

/**
 * The office pages as tiles (`D-347`).
 *
 * A Frappe workspace draws its links as lists of text, and ten of those were a
 * page of words a new customer had to read to find a door. The owner asked for
 * what Odoo and ERPNext 16 open on: a square with a picture and a name, and
 * nothing else.
 *
 * **The tiles are the page's own links, drawn another way.** A workspace's
 * record already holds its shortcuts and its cards; this asks the server for
 * them the way the desk does — so a link the reader may not open is already
 * gone, and a label is already theirs — and draws each as a tile. There is no
 * second list of screens to keep in step with the first (`CLAUDE.md` §5.5).
 *
 * It is mounted by one `Custom HTML Block` whose script asks for this bundle
 * and calls `restaurant_pos.desk_tiles(root_element)`, so what is stored in the
 * database never has to change when this does.
 */
frappe.provide("restaurant_pos");

const ICONS = {
	till: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
	guide: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.2a2.5 2.5 0 1 1 3.6 2.2c-.7.4-1.1 1-1.1 1.8M12 17h.01"/>',
	store: '<path d="M3 9l1.5-5h15L21 9"/><path d="M4 9v11h16V9"/><path d="M9 20v-6h6v6"/>',
	list: '<path d="M9 6h12M9 12h12M9 18h12"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/>',
	users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20v-1a6.5 6.5 0 0 1 13 0v1"/><path d="M16.5 4.8a3.5 3.5 0 0 1 0 6.4M21.5 20v-1a6 6 0 0 0-3.5-5.4"/>',
	table: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M9 10v10M15 10v10"/>',
	printer: '<path d="M7 9V3h10v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M7 14h10v7H7z"/>',
	tag: '<path d="M3 12V4h8l10 10-8 8z"/><circle cx="7.5" cy="8.5" r="1.5"/>',
	calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
	book: '<path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z"/><path d="M9 4v16"/>',
	chart: '<path d="M3 20h18"/><path d="M6 20v-8M11 20V5M16 20v-6M21 20V9"/>',
	gear: '<circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>',
	bolt: '<path d="M13 2.5L4.5 14H11l-1 7.5L18.5 10H12z"/>',
	file: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><path d="M9 13h6M9 17h6"/>',
};

/** A home tile's picture, by where it leads. */
const BY_ROUTE = {
	"/restaurant-pos": "till",
	"/rpos-guide": "guide",
	"/app/pos-branches-and-devices": "store",
	"/app/pos-menu": "list",
	"/app/pos-staff": "users",
	"/app/pos-floor": "table",
	"/app/printing": "printer",
	"/app/pos-offers-and-loyalty": "tag",
	"/app/pos-daily-work": "calendar",
	"/app/pos-books-and-logs": "book",
	"/app/pos-reports": "chart",
	"/app/pos-preferences": "gear",
};

const STYLE = `
	.rpos-tiles { padding: 4px 0 24px; }
	.rpos-group { margin: 22px 4px 10px; font-size: 13px; font-weight: 600; color: var(--text-muted); }
	.rpos-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(132px, 1fr)); gap: 14px; }
	.rpos-tile {
		display: flex; flex-direction: column; align-items: center; gap: 12px;
		padding: 20px 10px 16px; border-radius: 14px; cursor: pointer; text-decoration: none;
		background: var(--card-bg); border: 1px solid var(--border-color);
		transition: transform .15s ease, box-shadow .15s ease, border-color .15s ease;
	}
	.rpos-tile:hover, .rpos-tile:focus-visible {
		transform: translateY(-2px); border-color: #1f4d43; outline: none;
		box-shadow: 0 6px 18px rgba(31, 77, 67, .14);
	}
	.rpos-icon {
		width: 60px; height: 60px; border-radius: 16px; display: grid; place-items: center;
		background: #1f4d43; color: #fff;
	}
	.rpos-tile.is-till .rpos-icon { background: #1f9d6c; }
	.rpos-tile.is-guide .rpos-icon { background: #2f6fed; }
	.rpos-icon svg { width: 30px; height: 30px; fill: none; stroke: currentColor; stroke-width: 1.7;
		stroke-linecap: round; stroke-linejoin: round; }
	.rpos-name { font-size: 14px; font-weight: 600; line-height: 1.35; text-align: center; color: var(--text-color); }
	.rpos-empty { padding: 24px 4px; color: var(--text-muted); }
`;

function slug(name) {
	return frappe.router.slug(name);
}

/** Where a workspace link leads, as the desk itself would route it. */
function route_of(link) {
	if (link.link_type === "Report") {
		return link.is_query_report ? `/app/query-report/${encodeURIComponent(link.link_to)}` : `/app/${slug(link.link_to)}/view/report`;
	}
	if (link.link_type === "Page") return `/app/${link.link_to}`;
	return `/app/${slug(link.link_to)}`;
}

function icon_of(link) {
	if (link.link_type === "Report") return "chart";
	if (link.link_type === "Page") return "bolt";
	if (/settings|colours|theme/i.test(link.link_to)) return "gear";
	return "file";
}

function tile({ label, url, icon }) {
	const a = document.createElement("a");
	a.className = `rpos-tile is-${icon}`;
	a.href = url;
	a.innerHTML = `<span class="rpos-icon"><svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[icon] || ICONS.file}</svg></span>`;

	const name = document.createElement("span");
	name.className = "rpos-name";
	name.textContent = label;
	a.appendChild(name);

	// A desk page is opened by the desk's own router — no reload, and the back
	// button returns here. Anything else (the till, the guide) is a page of its
	// own and opens beside the office rather than replacing it.
	a.addEventListener("click", (event) => {
		if (event.ctrlKey || event.metaKey || event.shiftKey) return;
		event.preventDefault();
		if (url.startsWith("/app/")) frappe.set_route(url);
		else window.open(url, "_blank");
	});
	return a;
}

function grid(tiles) {
	const box = document.createElement("div");
	box.className = "rpos-grid";
	tiles.forEach((one) => box.appendChild(tile(one)));
	return box;
}

restaurant_pos.desk_tiles = async function (root) {
	const mount = root.querySelector(".rpos-tiles");
	if (!mount) return;

	const style = document.createElement("style");
	style.textContent = STYLE;
	root.appendChild(style);

	const route = frappe.get_route();
	const name = route[route.length - 1];
	let page;
	try {
		({ message: page } = await frappe.call("frappe.desk.desktop.get_desktop_page", {
			page: JSON.stringify({ name, title: name, public: 1 }),
		}));
	} catch (cause) {
		// The waiting line stays, and says what to do; a blank page says nothing.
		mount.querySelector(".rpos-wait")?.removeAttribute("hidden");
		throw cause;
	}

	mount.innerHTML = "";
	const shortcuts = (page?.shortcuts?.items || []).filter((row) => row.type === "URL" && row.url);
	const cards = (page?.cards?.items || []).filter((card) => (card.links || []).length);

	// The home page is its shortcuts; an area's page is its cards.
	if (shortcuts.length && !cards.length) {
		mount.appendChild(
			grid(shortcuts.map((row) => ({ label: __(row.label), url: row.url, icon: BY_ROUTE[row.url] || "file" }))),
		);
		return;
	}

	cards.forEach((card) => {
		if (cards.length > 1) {
			const heading = document.createElement("div");
			heading.className = "rpos-group";
			heading.textContent = __(card.label);
			mount.appendChild(heading);
		}
		mount.appendChild(
			grid(card.links.map((link) => ({ label: __(link.label), url: route_of(link), icon: icon_of(link) }))),
		);
	});

	if (!cards.length) {
		const none = document.createElement("div");
		none.className = "rpos-empty";
		none.textContent = __("Nothing on this page is open to you.");
		mount.appendChild(none);
	}
};

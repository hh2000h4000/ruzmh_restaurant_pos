// Copyright (c) 2026, RPOS and contributors
// For license information, please see license.txt

/**
 * A workspace shown as tiles (`D-348`).
 *
 * A Frappe workspace draws its cards as lists of text, and the office page was
 * a screen of words a new customer had to read to find a door. The owner asked
 * for what Odoo and ERPNext 16 open on — a square with a picture and a name —
 * and for the till's own habit: tap a group, see what is inside it.
 *
 * **It changes how the page's own widgets look, and nothing else.** The page
 * keeps its ordinary shortcuts and cards, added and ordered in Frappe's own
 * editor; this hides them and draws each as a tile. A card is a tile that
 * opens onto its links.
 *
 * The first version (`D-347`) kept the rows *out* of the page and drew them
 * from the record. Frappe deletes every row a saved page does not show, so the
 * owner's first edit emptied it. A page that survives being edited is one whose
 * widgets are really on it.
 *
 * **Any page becomes tiles by holding the `RPOS Tiles` block** — added from
 * the editor like any other block — so this is not the restaurant's alone.
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
	folder: '<path d="M3 6h7l2 2.5h9V19H3z"/>',
	back: '<path d="M9 6l6 6-6 6"/>',
};

/** The two doors that are not desk pages, known by where they lead. */
const OURS = {
	"/restaurant-pos": "till",
	"/rpos-guide": "guide",
};

const STYLE = `
	.rpos-tiled .ce-block:has(.links-widget-box),
	.rpos-tiled .ce-block:has(.shortcut-widget-box),
	.rpos-tiled .ce-block:has(.rpos-tiles-drawn) { display: none; }
	/* Editing is read off the widgets themselves — each carries \`edit-mode\` while
	   the editor is open — not off an ancestor: that class is not always there,
	   and without it the tiles sat over the widgets being edited. */
	.rpos-tiled:has(.widget.edit-mode) .ce-block { display: block !important; }
	.rpos-tiled:has(.widget.edit-mode) .rpos-tiles-view { display: none; }
	/* The editor leaves room under the last block for the next one; a page nobody is editing has no use for it. */
	.rpos-tiled .codex-editor__redactor { padding-bottom: 0 !important; }
	.rpos-tiled:has(.widget.edit-mode) .codex-editor__redactor { padding-bottom: 300px !important; }

	/* A row of its own among the editor's columns, whichever way they are laid out. */
	.rpos-tiles-view { padding: 8px 0 28px; grid-column: 1 / -1; flex: 0 0 100%; width: 100%; max-width: 100%; }
	.rpos-crumb { display: flex; align-items: center; gap: 10px; margin: 0 4px 16px; }
	.rpos-back {
		display: inline-flex; align-items: center; gap: 6px; padding: 7px 12px; border-radius: 10px;
		border: 1px solid var(--border-color); background: var(--card-bg); color: var(--text-color);
		font-size: 13px; font-weight: 600; cursor: pointer;
	}
	.rpos-back:hover { border-color: #1f4d43; }
	.rpos-back svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 2;
		stroke-linecap: round; stroke-linejoin: round; }
	.rpos-back.is-ltr svg { transform: scaleX(-1); }
	.rpos-here { font-size: 16px; font-weight: 700; color: var(--text-color); }
	.rpos-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(132px, 1fr)); gap: 14px; }
	.rpos-tile {
		display: flex; flex-direction: column; align-items: center; gap: 12px;
		padding: 20px 10px 16px; border-radius: 14px; cursor: pointer; text-decoration: none !important;
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
	.rpos-tile.is-link .rpos-icon { background: #e8efed; color: #1f4d43; }
	.rpos-icon svg { width: 30px; height: 30px; fill: none; stroke: currentColor; stroke-width: 1.7;
		stroke-linecap: round; stroke-linejoin: round; }
	.rpos-icon svg.icon { stroke: currentColor; fill: none; }
	.rpos-name { font-size: 14px; font-weight: 600; line-height: 1.35; text-align: center; color: var(--text-color); }
	.rpos-empty { padding: 24px 4px; color: var(--text-muted); }
`;

function styled() {
	if (document.getElementById("rpos-tiles-style")) return;
	const style = document.createElement("style");
	style.id = "rpos-tiles-style";
	style.textContent = STYLE;
	document.head.appendChild(style);
}

/** Where a workspace link leads, as the desk itself would route it. */
function route_of(link) {
	const slug = frappe.router.slug(link.link_to);
	if (link.link_type === "Report") {
		return link.is_query_report ? `/app/query-report/${encodeURIComponent(link.link_to)}` : `/app/${slug}/view/report`;
	}
	if (link.link_type === "Page") return `/app/${link.link_to}`;
	return `/app/${slug}`;
}

function picture(name, row_icon) {
	// The icon its row names wins: `rpos-…` is one of the set above, anything
	// else is one of Frappe's own, chosen in its editor — which is how a page
	// nobody here has heard of gets pictures of its own.
	if (row_icon?.startsWith("rpos-") && ICONS[row_icon.slice(5)]) name = row_icon.slice(5);
	else if (row_icon) return frappe.utils.icon(row_icon, "lg");
	return `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ICONS.file}</svg>`;
}

function tile({ label, kind, icon, row_icon, href, open }) {
	const a = document.createElement("a");
	a.className = `rpos-tile is-${kind}`;
	a.href = href || "#";
	a.innerHTML = `<span class="rpos-icon">${picture(icon, row_icon)}</span>`;

	const name = document.createElement("span");
	name.className = "rpos-name";
	name.textContent = label;
	a.appendChild(name);

	a.addEventListener("click", (event) => {
		if (href && (event.ctrlKey || event.metaKey || event.shiftKey)) return;
		event.preventDefault();
		open();
	});
	return a;
}

function grid(tiles) {
	const box = document.createElement("div");
	box.className = "rpos-grid";
	tiles.forEach((one) => box.appendChild(tile(one)));
	return box;
}

/** Leave the office for a screen: the desk's router for its own pages, a new tab for anything else. */
function go(url) {
	if (url.startsWith("/app/")) frappe.set_route(url);
	else window.open(url, "_blank");
}

function this_page(route) {
	const name = route[route.length - 1];
	const private_page = route[1] === "private";
	const known = (frappe.workspace?.all_pages || []).find(
		(page) => page.title === name && Boolean(page.public) === !private_page,
	);
	return known
		? { name: known.name, title: known.title, public: known.public }
		: { name, title: name, public: private_page ? 0 : 1 };
}

restaurant_pos.desk_tiles = async function (root) {
	styled();

	const host = root.host;
	const container = host.closest(".editor-js-container") || host.parentElement;
	container.classList.add("rpos-tiled");
	container.querySelectorAll(".rpos-tiles-view").forEach((old) => old.remove());

	// **Nothing of ours is in the page while it is being edited.** The tiles sit
	// among the editor's own blocks, and the editor refuses to save a page with
	// an element in it that it did not put there — the save simply did nothing.
	const editing = () => frappe.workspace?.is_read_only === false || Boolean(container.querySelector(".widget.edit-mode"));
	if (editing()) return;

	let page;
	try {
		({ message: page } = await frappe.call("frappe.desk.desktop.get_desktop_page", {
			page: JSON.stringify(this_page(frappe.get_route())),
		}));
	} catch (cause) {
		// The waiting line stays, and says what to do; a blank page says nothing.
		root.querySelector(".rpos-wait")?.removeAttribute("hidden");
		throw cause;
	}

	const shortcuts = page?.shortcuts?.items || [];
	const cards = (page?.cards?.items || []).filter((card) => (card.links || []).length);

	const view = document.createElement("div");
	view.className = "rpos-tiles-view";
	// **Where the block is, not at the top of the page.** On a page that also
	// has a heading, an onboarding guide or a chart, the tiles belong wherever
	// its owner dragged the block — the first try put them above everything,
	// over the guide a new user is meant to read first.
	const block = host.closest(".ce-block");
	if (block) block.after(view);
	else container.prepend(view);
	// Drawn: the block's own box has nothing left to say, so it goes with the
	// widgets it replaced.
	root.querySelector(".rpos-tiles")?.classList.add("rpos-tiles-drawn");
	block?.style.setProperty("display", "none");

	const watcher = new MutationObserver(() => {
		if (!editing()) return;
		view.remove();
		watcher.disconnect();
	});
	watcher.observe(container, { subtree: true, childList: true, attributes: true, attributeFilter: ["class"] });

	function home() {
		view.innerHTML = "";
		const tiles = [
			...shortcuts.map((row) => {
				const url = row.type === "URL" ? row.url : route_of({ link_to: row.link_to, link_type: row.type });
				const ours = OURS[row.url];
				return {
					label: __(row.label),
					kind: ours || "group",
					icon: ours || "file",
					row_icon: row.icon,
					href: url,
					open: () => go(url),
				};
			}),
			...cards.map((card) => ({
				label: __(card.label),
				kind: "group",
				icon: "folder",
				row_icon: card.icon,
				open: () => enter(card.label),
			})),
		];

		if (tiles.length) {
			view.appendChild(grid(tiles));
			return;
		}

		const none = document.createElement("div");
		none.className = "rpos-empty";
		none.textContent = __("Nothing on this page is open to you.");
		view.appendChild(none);
	}

	function inside(card) {
		view.innerHTML = "";

		const crumb = document.createElement("div");
		crumb.className = "rpos-crumb";
		const back = document.createElement("button");
		back.type = "button";
		back.className = frappe.utils.is_rtl() ? "rpos-back" : "rpos-back is-ltr";
		back.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS.back}</svg>`;
		back.appendChild(document.createTextNode(__("Back to the tiles")));
		back.addEventListener("click", () => history.back());
		const here = document.createElement("span");
		here.className = "rpos-here";
		here.textContent = __(card.label);
		crumb.append(back, here);
		view.appendChild(crumb);

		view.appendChild(
			grid(
				card.links.map((link) => {
					const url = route_of(link);
					const kind = link.link_type === "Report" ? "chart" : link.link_type === "Page" ? "bolt" : "file";
					return {
						label: __(link.label),
						kind: "link",
						icon: /settings|theme/i.test(link.link_to) ? "gear" : kind,
						row_icon: link.icon,
						href: url,
						open: () => go(url),
					};
				}),
			),
		);
	}

	function show(label) {
		const card = cards.find((one) => one.label === label);
		if (card) inside(card);
		else home();
	}

	// **The browser's back button is the way out of a group**, as it is the way
	// out of everything else on the desk. Entering one is a history entry, and
	// the page reads where it is from that entry — also when Frappe redraws it.
	function enter(label) {
		history.pushState({ ...(history.state || {}), rpos_card: label }, "");
		show(label);
	}

	restaurant_pos._tiles_pop && window.removeEventListener("popstate", restaurant_pos._tiles_pop);
	restaurant_pos._tiles_pop = (event) => {
		if (document.body.contains(view)) show(event.state?.rpos_card);
	};
	window.addEventListener("popstate", restaurant_pos._tiles_pop);

	show(history.state?.rpos_card);
};

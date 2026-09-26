# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The user guide, inside the system that it explains (`D-262`).

**Served here because the repository is private.** The guide was written in
`docs/guide` and read on GitHub, where a customer gets a 404. It now lives in
`public/guide` — the same Markdown, the same pictures, one copy — and this page
renders it for anyone signed in to the office, from «مساعدة ← دليل نقاط البيع».

**The Markdown stays GitHub-shaped.** Pages link to each other as `coupons.md`
and to pictures as `images/coupon-1.png`, which is what GitHub resolves. Those
two patterns are rewritten here and nowhere else, so a page reads the same in
both places and nobody writes a link twice.

**The order is the README's.** Its list is the sequence a restaurant sets up
and works in, and «السابق/التالي» at the foot of each page follow it;
`test_guide` holds every footer to that list so a page added later cannot sit
outside the chain.

**The filename is not a typo** — `www/rpos_card_sheet.py` records why Frappe
needs the underscores and why the `rpos-` prefix.

Refs: D-222, D-262
"""

import re
from pathlib import Path

import frappe
from frappe import _
from frappe.utils import md_to_html

GUIDE = Path(__file__).resolve().parent.parent / "public" / "guide"
ROUTE = "/rpos-guide"
IMAGES = "/assets/restaurant_pos/guide/images/"

#: A page is a Markdown file name and nothing else, so no path reaches outside.
NAME = re.compile(r"^[a-z0-9-]+$")

#: `[text](page.md)` in the README's list — the guide's order.
LISTED = re.compile(r"\[([^\]]+)\]\(([a-z0-9-]+)\.md\)")

# Every page is the same for every reader, but a page cached under its path
# would survive an edited guide until the cache is cleared.
no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=" + frappe.request.path
		raise frappe.Redirect

	page = frappe.form_dict.get("page")
	source = _source(page) if page else (GUIDE / "README.md").read_text(encoding="utf-8")

	context.no_cache = 1
	context.body = md_to_html(_linked(source))
	context.title = _heading(source) or _("POS User Guide")
	context.home = ROUTE
	context.lang = frappe.local.lang or "ar"
	context.text_direction = "rtl" if context.lang.startswith("ar") else "ltr"
	return context


def pages() -> list[tuple[str, str]]:
	"""`(file stem, title)` for every page, in the README's order."""
	readme = (GUIDE / "README.md").read_text(encoding="utf-8")
	return [(stem, title) for title, stem in LISTED.findall(readme)]


def _source(page: str) -> str:
	path = GUIDE / f"{page}.md"
	if not NAME.match(page) or not path.is_file():
		raise frappe.PageDoesNotExistError(_("There is no such page in the guide."))
	return path.read_text(encoding="utf-8")


def _linked(markdown: str) -> str:
	"""GitHub's relative links, turned into this site's routes."""
	markdown = re.sub(r"\]\(README\.md\)", f"]({ROUTE})", markdown)
	markdown = re.sub(r"\]\(([a-z0-9-]+)\.md\)", rf"]({ROUTE}/\1)", markdown)
	return markdown.replace("](images/", f"]({IMAGES}")


def _heading(markdown: str) -> str | None:
	match = re.search(r"^# (.+)$", markdown, re.MULTILINE)
	return match.group(1).strip() if match else None

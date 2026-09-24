# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Cards on A4, to print and cut up (`D-250`).

**The codes were being handed out on nothing.** A batch could be generated and
read off a list on screen, which is not something you give a guest. This is the
paper: ten cards to a sheet, each with the code large enough to read out and a
QR a scanner reads.

**The QR holds the bare code and nothing else.** Not a URL, not JSON. A till
scanner in keyboard-wedge mode types whatever it reads into the focused field
and presses Enter — which is exactly the field `CodePad` fills — so a QR
carrying `https://…/SAVE10` would type a URL into the coupon box and be refused.
The code alone is the one payload that works at the till *and* still shows the
guest their code when they point a phone at it.

**Printed from the browser, not rendered to PDF here.** The sheet carries Arabic
campaign names, and wkhtmltopdf's Arabic shaping is the reason every receipt in
this app prints as an image (`FR-7.4`). The browser already shapes Arabic
correctly and already has "Save as PDF" in its own print dialog, so the page
that prints is the page you see.

**The filename is not a typo, and the `rpos-` is not decoration.** Frappe looks
for a page's controller with the hyphens replaced by underscores, exactly as
`www/restaurant_pos.py` records; and `www` is one route namespace shared by
every installed app, so a page called `/coupon-sheet` is a name the next app
with coupons would take.

Refs: FR-11.1, D-250
"""

import json

import frappe
from frappe import _
from frappe.utils import formatdate

from restaurant_pos.utils.barcodes import qr_data_uri

#: Two columns by five rows. More per sheet means a code too small to read
#: across a counter, which is the only thing the card is for.
PER_SHEET = 10

#: A ceiling, not a page size: the sheet is printed from a list selection, and
#: Frappe's list view hands over at most 500 names at a time anyway.
MAX_CARDS = 500

# Rendered www pages are cached in redis **under their path alone** — the query
# string is not part of the key (`website/utils.py:cache_html`). Without this
# flag the first selection printed would be served to every later one.
no_cache = 1


def get_context(context):
	frappe.has_permission("POS Coupon", "read", throw=True)

	coupons, capped = _chosen()
	if not coupons:
		frappe.throw(_("Select the coupons to print first."), frappe.ValidationError)

	context.no_cache = 1
	context.per_sheet = PER_SHEET
	context.capped = capped
	context.coupons = [_card(coupon) for coupon in coupons]
	context.title = _("Coupons")
	# Set here rather than read off `frappe` in the template: a standalone page
	# skips the website base template, and with it everything that base template
	# would have worked out about direction.
	context.lang = frappe.local.lang or "ar"
	context.text_direction = "rtl" if context.lang.startswith("ar") else "ltr"
	return context


def _chosen() -> tuple[list[dict], bool]:
	"""The coupons named in the query string, in the order they were issued.

	Also whether the ceiling cut the list short, because a sheet that quietly
	prints 500 of the 900 cards somebody asked for is a sheet they will hand out
	believing it is complete.
	"""
	names = frappe.form_dict.get("names")
	try:
		names = json.loads(names) if names else []
	except ValueError:
		names = []

	names = [str(name) for name in names]
	capped = len(names) > MAX_CARDS
	names = names[:MAX_CARDS]
	if not names:
		return [], False

	return frappe.get_all(
		"POS Coupon",
		filters={"name": ("in", names)},
		fields=["name", "coupon_code", "campaign", "promotion", "valid_from", "valid_to", "max_uses"],
		order_by="creation asc",
	), capped


def _card(coupon: dict) -> dict:
	"""One card's worth of text, composed here so the template only lays it out."""
	coupon = dict(coupon)
	coupon["qr"] = qr_data_uri(coupon["coupon_code"])

	offer = (
		frappe.get_cached_value(
			"Restaurant Promotion",
			coupon["promotion"],
			["title_ar", "title", "valid_from", "valid_to"],
			as_dict=True,
		)
		or frappe._dict()
	)

	# The offer's own name, because a card has to say what the code is worth.
	# Arabic first, like everywhere else a promotion is named to somebody who is
	# not the manager — the guest holding this card reads Arabic.
	coupon["offer"] = offer.title_ar or offer.title or ""

	# **The offer's dates when the coupon carries none.** Leaving them blank on
	# the coupon means "whatever the offer says" (it is what the guide tells the
	# manager), so a card printed from a blank pair would promise a code with no
	# end while the offer expires on Thursday.
	coupon["valid"] = _window(
		coupon.get("valid_from") or offer.valid_from,
		coupon.get("valid_to") or offer.valid_to,
	)

	# A shared code says nothing; a single-use one has to say so, or the guest
	# who tries it twice thinks the card was faulty.
	coupon["one_use"] = coupon.get("max_uses") == 1
	return coupon


def _window(start, end) -> str:
	"""How long the card is good for, said the way a guest reads it."""
	if start and end:
		return _("Valid {0} to {1}").format(formatdate(start), formatdate(end))
	if end:
		return _("Valid until {0}").format(formatdate(end))
	if start:
		return _("Valid from {0}").format(formatdate(start))
	return ""

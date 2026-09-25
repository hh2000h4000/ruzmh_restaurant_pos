# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Cards on A4, to print and cut up — coupons or gift cards (`D-250`, `D-259`).

**One page, because it is one question.** *Print these codes as cards* is the
same request whether the code unlocks an offer or carries a balance, and the
only difference is the two or three lines under the number. So `kind` chooses
the source and the wording; everything about paper, cutting lines, the QR and
the layout is shared (`CLAUDE.md` §5.5 — the difference is a prop, not a second
screen).

**The QR holds the bare code and nothing else.** Not a URL, not JSON. A till
scanner in keyboard-wedge mode types whatever it reads into the focused field
and presses Enter — which is exactly the field `CodePad` fills — so a QR
carrying `https://…/SAVE10` would type a URL into the box and be refused. The
code alone is the one payload that works at the till *and* still shows the guest
their code when they point a phone at it.

**Printed from the browser, not rendered to PDF here.** The sheet carries Arabic
names, and wkhtmltopdf's Arabic shaping is the reason every receipt in this app
prints as an image (`FR-7.4`). The browser already shapes Arabic correctly and
already has "Save as PDF" in its own print dialog, so the page that prints is
the page you see.

**The filename is not a typo, and the `rpos-` is not decoration.** Frappe looks
for a page's controller with the hyphens replaced by underscores, exactly as
`www/restaurant_pos.py` records; and `www` is one route namespace shared by
every installed app, so a page called `/card-sheet` is a name the next app with
cards would take.

Refs: FR-11.1, FR-11.5, D-250, D-259
"""

import json

import frappe
from frappe import _
from frappe.utils import flt, formatdate

from restaurant_pos.utils.barcodes import qr_data_uri

#: Two columns by five rows. More per sheet means a code too small to read
#: across a counter, which is the only thing the card is for.
PER_SHEET = 10

#: A ceiling, not a page size: the sheet is printed from a list selection, and
#: Frappe's list view hands over at most 500 names at a time anyway.
MAX_CARDS = 500

#: What each kind is called, and where its cards come from.
KINDS = ("coupon", "gift")

# Rendered www pages are cached in redis **under their path alone** — the query
# string is not part of the key (`website/utils.py:cache_html`). Without this
# flag the first selection printed would be served to every later one.
no_cache = 1


def get_context(context):
	kind = frappe.form_dict.get("kind") or "coupon"
	if kind not in KINDS:
		frappe.throw(_("There is no such card sheet."), frappe.ValidationError)

	doctype = "POS Gift Card" if kind == "gift" else "POS Coupon"
	frappe.has_permission(doctype, "read", throw=True)

	names, capped = _chosen()
	cards = _gift_cards(names) if kind == "gift" else _coupons(names)
	if not cards:
		frappe.throw(_("Select what to print first."), frappe.ValidationError)

	context.no_cache = 1
	context.per_sheet = PER_SHEET
	context.capped = capped
	context.cards = cards
	context.title = _("Gift cards") if kind == "gift" else _("Coupons")
	# Set here rather than read off `frappe` in the template: a standalone page
	# skips the website base template, and with it everything that base template
	# would have worked out about direction.
	context.lang = frappe.local.lang or "ar"
	context.text_direction = "rtl" if context.lang.startswith("ar") else "ltr"
	return context


def _chosen() -> tuple[list[str], bool]:
	"""The records named in the query string.

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
	return names[:MAX_CARDS], len(names) > MAX_CARDS


# --------------------------------------------------------------------------- #
# Coupons
# --------------------------------------------------------------------------- #


def _coupons(names: list[str]) -> list[dict]:
	if not names:
		return []

	rows = frappe.get_all(
		"POS Coupon",
		filters={"name": ("in", names)},
		fields=["name", "coupon_code", "campaign", "promotion", "valid_from", "valid_to", "max_uses"],
		order_by="creation asc",
	)
	return [_coupon_card(row) for row in rows]


def _coupon_card(coupon: dict) -> dict:
	"""One card's worth of text, composed here so the template only lays it out."""
	offer = (
		frappe.get_cached_value(
			"Restaurant Promotion",
			coupon["promotion"],
			["title_ar", "title", "valid_from", "valid_to"],
			as_dict=True,
		)
		or frappe._dict()
	)

	# **The offer's dates when the coupon carries none.** Leaving them blank on
	# the coupon means "whatever the offer says" (it is what the guide tells the
	# manager), so a card printed from a blank pair would promise a code with no
	# end while the offer expires on Thursday.
	valid = _window(coupon.get("valid_from") or offer.valid_from, coupon.get("valid_to") or offer.valid_to)

	# A shared code says nothing; a single-use one has to say so, or the guest
	# who tries it twice thinks the card was faulty.
	once = _("One use only") if coupon.get("max_uses") == 1 else ""

	return {
		"code": coupon["coupon_code"],
		"qr": qr_data_uri(coupon["coupon_code"]),
		# The offer's own name, because a card has to say what the code is worth.
		# Arabic first, like everywhere else a promotion is named to somebody who
		# is not the manager — the guest holding this card reads Arabic.
		"title": offer.title_ar or offer.title or "",
		"lines": [line for line in (coupon.get("campaign"), valid, once) if line],
	}


# --------------------------------------------------------------------------- #
# Gift cards
# --------------------------------------------------------------------------- #


def _gift_cards(names: list[str]) -> list[dict]:
	if not names:
		return []

	rows = frappe.get_all(
		"POS Gift Card",
		filters={"name": ("in", names)},
		fields=["name", "card_number", "balance", "initial_value", "expires_on"],
		order_by="creation asc",
	)
	return [_gift_card(row) for row in rows]


def _gift_card(card: dict) -> dict:
	"""**The balance, not the face value.**

	A card printed after it has been part spent must say what is on it now —
	printing the two hundred it was sold with would hand a guest a card claiming
	money it no longer has, and the argument at the counter is the restaurant's.
	"""
	return {
		"code": card["card_number"],
		"qr": qr_data_uri(card["card_number"]),
		"title": _("Gift card"),
		"lines": [
			line
			for line in (
				_("Balance {0}").format(f"{flt(card.get('balance')):.2f}"),
				_("Valid until {0}").format(formatdate(card["expires_on"])) if card.get("expires_on") else "",
			)
			if line
		],
	}


def _window(start, end) -> str:
	"""How long the card is good for, said the way a guest reads it."""
	if start and end:
		return _("Valid {0} to {1}").format(formatdate(start), formatdate(end))
	if end:
		return _("Valid until {0}").format(formatdate(end))
	if start:
		return _("Valid from {0}").format(formatdate(start))
	return ""

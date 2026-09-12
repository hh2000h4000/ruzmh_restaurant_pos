# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The brand colours a terminal renders with (`FR-15.1` to `FR-15.6`, `D-198`).

The tokens travel in the login payload and are written to CSS custom properties
by `stores/theme.ts`; no component carries a brand colour, which is what made
theming a record rather than a rewrite (`D-014`).

**Readability is validated here, not left to taste** (`FR-15.3`): a cashier
reads this screen under restaurant lighting, at speed, from a metre away. Each
foreground/background pair must clear the 4.5:1 ratio `06` §Accessibility
requires, and the same three pairs are checked again in the browser for a theme
that arrived from an older server.

**Status colours are not here** (`FR-15.5`): available, occupied, reserved and
the order statuses are fixed, because staff act on them and they are the danger
signal before a destructive step.
"""

import frappe
from frappe import _

#: The house look: the fallback when no theme is set, and the value of any token
#: a theme leaves empty. It is also written in `frontend/src/styles/tokens.css`,
#: so **both carry these values** or a terminal shows one for a moment and then
#: the other.
HOUSE = {
	"primary": "#1F4B43",
	"primary_contrast": "#F6F4F0",
	"secondary": "#2F6D61",
	"secondary_contrast": "#F6F4F0",
	"surface": "#FFFFFF",
	"background": "#F3F1ED",
	"text": "#14171A",
	"brand_logo": None,
}

#: token in the payload -> field on `RPOS Theme`.
FIELDS = {
	"primary": "primary_color",
	"primary_contrast": "primary_contrast",
	"secondary": "secondary_color",
	"secondary_contrast": "secondary_contrast",
	"surface": "surface_color",
	"background": "background_color",
	"text": "text_color",
	"brand_logo": "brand_logo",
}

#: (background, foreground) a cashier has to read one against the other.
PAIRS = (
	("primary", "primary_contrast"),
	("secondary", "secondary_contrast"),
	("background", "text"),
)

MINIMUM_CONTRAST = 4.5


def tokens(profile) -> dict:
	"""The colours this terminal renders with (`FR-15.2`).

	Its own theme, else its branch's, else the one marked default — first match
	wins, so a chain brands each branch and a single restaurant sets one theme
	and never thinks about it again. With none set, the house look: a terminal is
	never unstyled, offline or on (`FR-15.6`).
	"""
	name = _resolve(profile)
	if not name:
		return dict(HOUSE)

	theme = frappe.get_cached_doc("RPOS Theme", name)
	return {token: theme.get(field) or HOUSE[token] for token, field in FIELDS.items()}


def _resolve(profile) -> str | None:
	own = profile.get("rpos_theme")
	if _usable(own):
		return own

	branch = frappe.db.get_value("Branch", profile.branch, "rpos_theme") if profile.get("branch") else None
	if _usable(branch):
		return branch

	return frappe.db.get_value("RPOS Theme", {"is_default": 1, "is_active": 1}, "name")


def _usable(name: str | None) -> bool:
	"""A theme switched off is not a theme: the next one down answers.

	Otherwise switching one off would leave the terminals that name it with no
	colours at all, which is the one thing `FR-15.6` forbids.
	"""
	return bool(name) and bool(frappe.db.get_value("RPOS Theme", name, "is_active"))


#: The two colours text is ever set in here. One of them always clears the
#: minimum against any colour on earth: the hardest case is a mid-tone at 0.179
#: luminance, where both land on 4.58:1 — above the 4.5 the screen needs.
INK = "#000000"
PAPER = "#FFFFFF"


def readable_on(colour: str | None) -> str:
	"""Black or white on `colour`, whichever a cashier reads more easily.

	**A restaurant knows its brand colour; it does not know its contrast ratio**
	(`D-199`). So the colour that has to be *read* on a brand colour is
	arithmetic, not a question — asked of every "text on" field left empty, and
	it can never produce a refusal.
	"""
	return INK if contrast(colour, INK) >= contrast(colour, PAPER) else PAPER


def contrast(first: str | None, second: str | None) -> float:
	"""The WCAG 2.1 contrast ratio between two hex colours, 1.0 to 21.0."""
	light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
	return (light + 0.05) / (dark + 0.05)


def _luminance(colour: str | None) -> float:
	"""Relative luminance, per WCAG 2.1."""
	channels = []
	for value in _channels(colour):
		fraction = value / 255
		channels.append(fraction / 12.92 if fraction <= 0.03928 else ((fraction + 0.055) / 1.055) ** 2.4)

	red, green, blue = channels
	return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _channels(colour: str | None) -> tuple[int, int, int]:
	value = (colour or "").strip().lstrip("#")
	if len(value) == 3:
		value = "".join(character * 2 for character in value)

	try:
		number = int(value, 16)
	except ValueError:
		number = -1
	if len(value) != 6 or number < 0:
		frappe.throw(_("{0} is not a colour.").format(colour or "—"))

	return (number >> 16) & 255, (number >> 8) & 255, number & 255

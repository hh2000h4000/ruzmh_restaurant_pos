# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Files the till draws, which have to be files a cashier may fetch.

Refs: D-197, D-198
"""

import frappe
from frappe import _


def assert_public(doc, fields: tuple[str, ...]) -> None:
	"""Refuse a private file on a picture the till shows.

	A private file is served only to someone allowed to read the record it hangs
	on, and a cashier reads neither the settings page nor the theme: every tile
	would draw a broken picture, on every terminal, with nothing on screen saying
	why. The upload defaults to public; this catches a path typed by hand.

	One function rather than one per controller — the same question asked of the
	settings page and of the theme's logo (`CLAUDE.md` §5.5).
	"""
	for field in fields:
		if (doc.get(field) or "").startswith("/private/"):
			frappe.throw(
				_(
					"{0} is a private file, and the till cannot show it to a cashier. Upload it as public."
				).format(_(doc.meta.get_label(field)))
			)

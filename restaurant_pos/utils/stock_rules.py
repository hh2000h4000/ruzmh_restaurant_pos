# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The stock settings, kept from contradicting each other (`D-337`).

Two settings, two questions:

* **The branch — the till.** "Refuse a sale when stock is short": is the cashier
  stopped when the bottle runs out?
* **The site — the books.** ERPNext's "Allow Negative Stock": when the day is
  posted and something is short, does the stock ledger go below zero, or does
  the posting stop until the purchase is entered?

Three of the four combinations are a restaurant somebody runs. The fourth is a
contradiction: a branch that refuses nothing on a site that allows no negative
sells freely all day and cannot post its stock at night. So **the site's setting
is the ceiling**: where negative stock is not allowed, every branch enforces.

And one warehouse, not two. The branch names where its stock comes from, and its
terminals take that — `POS Profile.warehouse` is what ERPNext reads, so it is
filled from the branch rather than asked for a second time. A branch's field
that nothing read was a required question with no effect.
"""

import frappe
from frappe import _
from frappe.utils import cint, get_link_to_form

ENFORCE = "rpos_enforce_stock"


def negative_stock_allowed() -> bool:
	return bool(cint(frappe.db.get_single_value("Stock Settings", "allow_negative_stock")))


# --------------------------------------------------------------------------- #
# The ceiling
# --------------------------------------------------------------------------- #


def keep_under_the_ceiling(doc, method=None) -> None:
	"""`Branch.validate` — a branch refuses nothing only where the books can take the shortfall."""
	if cint(doc.get(ENFORCE)) or negative_stock_allowed():
		return

	if doc.is_new():
		# The form opens unticked on every site; here that would be the
		# contradiction, so the branch starts the only way it can.
		doc.set(ENFORCE, 1)
		return

	if doc.has_value_changed(ENFORCE):
		frappe.throw(
			_(
				"This site does not allow negative stock, so a branch cannot sell without checking: "
				"the day's stock could never be posted. Keep this ticked, or allow negative stock in {0} first."
			).format(get_link_to_form("Stock Settings", "Stock Settings", _("Stock Settings")))
		)


def warn_when_the_ceiling_drops(doc, method=None) -> None:
	"""`Stock Settings.validate` — say which branches no longer fit, when negative stock is turned off."""
	if cint(doc.allow_negative_stock) or not doc.has_value_changed("allow_negative_stock"):
		return

	loose = frappe.get_all("Branch", filters={ENFORCE: 0}, pluck="name")
	if loose:
		frappe.msgprint(
			_(
				"These branches sell without checking stock: {0}. With negative stock not allowed, their "
				"day's stock will not post whenever something is short. Tick «Refuse a Sale When Stock Is "
				"Short» on each, or allow negative stock."
			).format(", ".join(loose)),
			title=_("Branches that no longer fit"),
			indicator="orange",
		)


# --------------------------------------------------------------------------- #
# One warehouse
# --------------------------------------------------------------------------- #


def move_the_terminals_with_the_branch(doc, method=None) -> None:
	"""`Branch.on_update` — terminals that were on the branch's warehouse follow it to the new one.

	A terminal set to a different warehouse on purpose — a branch with a second
	store room — is left where it was put.
	"""
	before = doc.get_doc_before_save()
	was = before.get("default_warehouse") if before else None
	if not was or was == doc.get("default_warehouse"):
		return

	from restaurant_pos.utils.order import profiles_in

	for profile in profiles_in(doc.name):
		if frappe.db.get_value("POS Profile", profile, "warehouse") == was:
			frappe.db.set_value("POS Profile", profile, "warehouse", doc.default_warehouse)
			frappe.clear_document_cache("POS Profile", profile)


# --------------------------------------------------------------------------- #
# Said on the form
# --------------------------------------------------------------------------- #


def say_the_site_setting(doc, method=None) -> None:
	"""`onload` — the site's setting, read out where the branch's and the till's are set.

	One sentence built here, so the two forms that show it cannot word it two
	ways; each form only draws what it is handed.
	"""
	where = get_link_to_form("Stock Settings", "Stock Settings", _("Stock Settings"))
	if negative_stock_allowed():
		note = _(
			"<b>Negative stock: allowed.</b> When a day is posted and an ingredient is short, it goes "
			"below zero and the next purchase corrects it. Enter purchases before the month is closed. "
			"Changed in {0}."
		)
	else:
		note = _(
			"<b>Negative stock: not allowed.</b> When a day is posted and an ingredient is short, the "
			"stock posting stops and says what is missing; the accounts post anyway. Every branch must "
			"then refuse a sale when stock is short. Changed in {0}."
		)
	doc.set_onload("rpos_stock_note", note.format(where))

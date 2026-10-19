# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""What the restaurant still owes on gift cards, on a chosen day (`D-259`).

**The figure an accountant reconciles with.** Money taken for a card is a
liability until the guest eats it (`D-256`), and the ledger carries that in one
account. This is the other side of the same number, card by card — so a total
that does not match the account's balance is a question somebody can actually
chase rather than a discrepancy with nowhere to start.

**As at a date, not as of now.** A month-end entry is made against the thirtieth,
often in the second week of the next month, and a balance read today would
include cards sold and spent since. So the balance is summed from the entries up
to that day rather than read off `POS Gift Card.balance`, which is only ever
current.

**Expired and switched-off cards are still listed, and still owed** — unless a
policy says otherwise, which is the accountant's call and not a report's. They
are marked so the decision can be made on sight.

Refs: FR-11.5, D-256, D-259
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from restaurant_pos.utils.bulk import get_all_in
from restaurant_pos.utils.gift_card import ADDS, TAKES
from restaurant_pos.utils.totals import money


def execute(filters=None):
	filters = frappe._dict(filters or {})
	on = getdate(filters.on or today())

	cards = frappe.get_all(
		"POS Gift Card",
		filters={"issued_branch": filters.branch} if filters.branch else None,
		fields=[
			"name",
			"card_number",
			"customer",
			"issued_branch",
			"issued_at",
			"expires_on",
			"is_active",
			"initial_value",
		],
		order_by="issued_at asc",
	)
	if not cards:
		return _columns(), []

	balances = _balances_on(on, [row.name for row in cards])

	rows = []
	for card in cards:
		# A card issued after the date did not exist yet — it owes nothing on a
		# day it had not been sold on.
		if card.issued_at and getdate(card.issued_at) > on:
			continue

		balance = balances.get(card.name, 0.0)
		if filters.hide_empty and not balance:
			continue

		rows.append(
			{
				"gift_card": card.name,
				"card_number": card.card_number,
				"customer": card.customer,
				"branch": card.issued_branch,
				"issued_at": card.issued_at,
				"initial_value": money(card.initial_value),
				"balance": balance,
				"note": _note(card, on),
			}
		)

	return _columns(), rows


def _balances_on(on, cards: list[str]) -> dict[str, float]:
	"""Each card's balance as at the end of that day, from its entries."""
	tally: dict[str, float] = {}

	for row in get_all_in(
		"POS Gift Card Entry",
		filters={"gift_card": ("in", cards), "recorded_at": ("<=", f"{on} 23:59:59")},
		fields=["gift_card", "entry_type", "amount"],
	):
		if row.entry_type in ADDS:
			change = flt(row.amount)
		elif row.entry_type in TAKES:
			change = -flt(row.amount)
		else:
			change = 0.0

		tally[row.gift_card] = tally.get(row.gift_card, 0.0) + change

	return {card: money(amount) for card, amount in tally.items()}


def _note(card, on) -> str:
	"""Why a balance might not be owed after all — said, not decided."""
	if not card.is_active:
		return _("Switched off")

	if card.expires_on and getdate(card.expires_on) < on:
		return _("Expired {0}").format(card.expires_on)

	return ""


def _columns() -> list[dict]:
	return [
		{
			"fieldname": "card_number",
			"label": _("Card Number"),
			"fieldtype": "Link",
			"options": "POS Gift Card",
			"width": 140,
		},
		{
			"fieldname": "customer",
			"label": _("Customer"),
			"fieldtype": "Link",
			"options": "Customer",
			"width": 180,
		},
		{
			"fieldname": "branch",
			"label": _("Issued Branch"),
			"fieldtype": "Link",
			"options": "Branch",
			"width": 120,
		},
		{"fieldname": "issued_at", "label": _("Issued"), "fieldtype": "Datetime", "width": 160},
		{
			"fieldname": "initial_value",
			"label": _("Sold For"),
			"fieldtype": "Currency",
			"width": 110,
		},
		{"fieldname": "balance", "label": _("Balance"), "fieldtype": "Currency", "width": 110},
		{"fieldname": "note", "label": _("Note"), "fieldtype": "Data", "width": 140},
	]

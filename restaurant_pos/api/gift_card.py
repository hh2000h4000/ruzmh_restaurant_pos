# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Gift cards at the till (`D-256`).

Two questions, and they are different ones: *sell me a card* needs a number that
does not exist yet and an amount, *what is on this card* needs a number that
does. So two endpoints, and the till asks them from two places.

Refs: FR-11.5, D-256
"""

import frappe

from restaurant_pos.utils import gift_card as cards
from restaurant_pos.utils.permissions import assert_pos_user


@frappe.whitelist(methods=["POST"])
def sell(
	pos_profile: str,
	card_number: str,
	amount: float,
	mode_of_payment: str,
	customer: str | None = None,
	expires_on: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Sell one card. Every guard the money needs is inside `utils.gift_card.issue`."""
	assert_pos_user()

	return cards.issue(
		pos_profile,
		card_number=card_number,
		amount=amount,
		mode_of_payment=mode_of_payment,
		customer=customer,
		expires_on=expires_on,
		queue_id=queue_id,
	)


@frappe.whitelist(methods=["GET"])
def lookup(card_number: str) -> dict:
	"""What is on a card, for the screen that is about to spend it.

	**Refusals come back as refusals**, not as a zero balance: *no such card*,
	*switched off* and *expired* are three different things for the cashier to
	say to the guest, and `find` already words each of them.
	"""
	assert_pos_user()

	card = cards.find(card_number)
	return {
		"gift_card": card.name,
		"card_number": card.card_number,
		"balance": cards.balance_of(card.card_number),
		"expires_on": card.expires_on,
	}

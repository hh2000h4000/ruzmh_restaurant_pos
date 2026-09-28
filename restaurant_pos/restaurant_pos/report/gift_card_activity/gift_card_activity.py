# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""What moved on gift cards over a period — sold, topped up, spent, given back.

`Gift Card Balances` answers «what do we owe on the thirtieth»; nothing answered
«how many cards did we sell this month, and how much of it was spent». Square's
and Toast's gift card reports are this: the loads and the redemptions of a
period side by side, and the list behind them.

**A line per movement**, read from the card's own ledger (`POS Gift Card Entry`),
the same rows the balance is summed from — so the change in owed money this
report shows is the difference between two `Gift Card Balances` dates, and the
two cannot disagree. The summary above the table names each kind apart: selling
a card is money in, spending it is a sale paid for (`D-256`), and a void is an
issue taken back (`D-267`).

Refs: FR-11.5, D-256, D-267
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate

from restaurant_pos.utils.gift_card import ADDS
from restaurant_pos.utils.totals import money

KINDS = ("issue", "top_up", "redeem", "refund", "void")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date, to_date = getdate(filters.from_date), getdate(filters.to_date)

	# Up to the start of the day after, then trimmed: `between` on a datetime
	# against a bare date stops at midnight and loses the last day's evening.
	conditions = {"recorded_at": ("between", [from_date, add_days(to_date, 1)])}
	if filters.branch:
		conditions["branch"] = filters.branch
	if filters.pos_profile:
		conditions["pos_profile"] = filters.pos_profile
	if filters.entry_type:
		conditions["entry_type"] = filters.entry_type

	rows = frappe.get_all(
		"POS Gift Card Entry",
		filters=conditions,
		fields=[
			"recorded_at",
			"gift_card",
			"entry_type",
			"amount",
			"balance_after",
			"sales_invoice",
			"mode_of_payment",
			"branch",
			"recorded_by",
			"reason",
		],
		order_by="recorded_at asc",
		limit_page_length=0,
	)
	rows = [row for row in rows if getdate(row.recorded_at) <= to_date]

	numbers = _card_numbers({row.gift_card for row in rows})
	totals = dict.fromkeys(KINDS, 0.0)
	for row in rows:
		row["card_number"] = numbers.get(row.gift_card, row.gift_card)
		row["kind"] = _(row.entry_type, context="POS Gift Card Entry")
		row["amount"] = money(row.amount)
		# Signed as the debt moves: a card sold is more owed, a card spent is less.
		row["owed_change"] = row["amount"] if row.entry_type in ADDS else -row["amount"]
		totals[row.entry_type] = totals.get(row.entry_type, 0.0) + row["amount"]

	return _columns(), rows, None, None, _summary(totals)


def _card_numbers(cards: set) -> dict:
	if not cards:
		return {}
	return dict(
		frappe.get_all(
			"POS Gift Card",
			filters={"name": ("in", list(cards))},
			fields=["name", "card_number"],
			as_list=True,
		)
	)


def _summary(totals: dict) -> list[dict]:
	change = sum(amount if kind in ADDS else -amount for kind, amount in totals.items())
	lines = [
		(_("Cards Sold"), totals["issue"], "Blue"),
		(_("Topped Up"), totals["top_up"], "Blue"),
		(_("Spent"), totals["redeem"], "Green"),
		(_("Refunded to Cards"), totals["refund"], "Orange"),
		(_("Voided"), totals["void"], "Red"),
		(_("Change in Owed"), change, "Gray"),
	]
	return [
		{"label": label, "value": money(value), "datatype": "Currency", "indicator": colour}
		for label, value, colour in lines
	]


def _columns() -> list[dict]:
	return [
		{
			"fieldname": "recorded_at",
			"label": _("Date", context="RPOS report"),
			"fieldtype": "Datetime",
			"width": 160,
		},
		{"fieldname": "card_number", "label": _("Card Number"), "fieldtype": "Data", "width": 150},
		{"fieldname": "kind", "label": _("Movement"), "fieldtype": "Data", "width": 110},
		{
			"fieldname": "amount",
			"label": _("Amount", context="RPOS report"),
			"fieldtype": "Currency",
			"width": 110,
		},
		{"fieldname": "owed_change", "label": _("Change in Owed"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "balance_after", "label": _("Balance After"), "fieldtype": "Currency", "width": 120},
		{
			"fieldname": "sales_invoice",
			"label": _("Invoice", context="RPOS report"),
			"fieldtype": "Link",
			"options": "Sales Invoice",
			"width": 150,
		},
		{
			"fieldname": "mode_of_payment",
			"label": _("Paid With"),
			"fieldtype": "Link",
			"options": "Mode of Payment",
			"width": 120,
		},
		{
			"fieldname": "branch",
			"label": _("Branch", context="RPOS report"),
			"fieldtype": "Link",
			"options": "Branch",
			"width": 130,
		},
		{
			"fieldname": "recorded_by",
			"label": _("By", context="RPOS report"),
			"fieldtype": "Link",
			"options": "User",
			"width": 150,
		},
		{
			"fieldname": "reason",
			"label": _("Reason", context="RPOS report"),
			"fieldtype": "Data",
			"width": 200,
		},
	]

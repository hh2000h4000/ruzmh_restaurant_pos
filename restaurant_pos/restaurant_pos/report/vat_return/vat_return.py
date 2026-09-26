# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The VAT return, box by box, as ZATCA's form lays it out (`D-273`).

**Why it is here.** A restaurant files a VAT return every month or quarter, and
ERPNext v15 no longer ships its Saudi one (the regional report left the core);
the ZATCA app on the user's site reports its integration, not the return. So an
accountant was adding up invoices by hand.

**The form's own boxes and columns** — amount, adjustment, VAT — so each line is
copied across as it stands. **Credit notes are adjustments**, which is where the
form puts them.

**VAT is what landed on the VAT accounts**, not every charge on an invoice: the
accounts named in the company's tax templates. A delivery fee on the same bill is
not tax.

**A bill with no VAT is zero-rated or exempt, and the books cannot say which.**
Both boxes take their sales from the item's tax category, which a restaurant
almost never has; such sales are shown once, in box 3, and said so. The same for
purchases in boxes 10 and 11.

**What the system does not hold is left blank and named:** private healthcare
and education (2), exports (4), imports (8, 9), corrections from a previous
return (14) and credit carried forward (15).

**And the last line is the books:** the movement on the same VAT accounts for the
period, which box 13 must equal — or the difference is something to ask about.

Refs: FR-11.2, D-273
"""

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import flt

from restaurant_pos.utils import reporting
from restaurant_pos.utils.company import site_company

SIDES = {
	"sales": ("Sales Invoice", "Sales Taxes and Charges", "Sales Taxes and Charges Template"),
	"purchases": ("Purchase Invoice", "Purchase Taxes and Charges", "Purchase Taxes and Charges Template"),
}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	# The site's company when nothing is chosen — the user's has no default set
	# anywhere, and one company is not a guess (`gift_card_accounts`).
	filters.company = site_company(filters.company)
	if not filters.company:
		frappe.throw(_("Choose the company."))
	from_date, to_date = (value[:10] for value in reporting.window(filters))

	accounts = vat_accounts(filters.company)
	sales = _side("sales", filters.company, from_date, to_date, accounts)
	purchases = _side("purchases", filters.company, from_date, to_date, accounts)

	rows = _rows(sales, purchases)
	rows.append(_books(filters.company, from_date, to_date, accounts, rows))
	return _columns(), rows


def vat_accounts(company: str) -> set[str]:
	"""Every account a tax template of this company charges VAT to."""
	accounts: set[str] = set()
	for _doctype, child, template in SIDES.values():
		templates = frappe.get_all(template, filters={"company": company}, pluck="name")
		if templates:
			accounts.update(
				frappe.get_all(
					child,
					filters={"parenttype": template, "parent": ("in", templates), "rate": (">", 0)},
					pluck="account_head",
				)
			)
	return accounts


def _side(side: str, company: str, from_date: str, to_date: str, accounts: set[str]) -> dict:
	"""Net and VAT, split into taxed and untaxed, sales against their credit notes."""
	doctype, child, _template = SIDES[side]
	invoices = frappe.get_all(
		doctype,
		filters={"company": company, "docstatus": 1, "posting_date": ("between", [from_date, to_date])},
		fields=["name", "is_return", "base_net_total"],
	)

	vat = _vat_by_invoice(doctype, child, [row.name for row in invoices], accounts) if invoices else {}

	totals = {
		kind: {"amount": 0.0, "adjustment": 0.0, "vat": 0.0, "vat_adjustment": 0.0}
		for kind in ("taxed", "untaxed")
	}
	for row in invoices:
		tax = vat.get(row.name, 0.0)
		line = totals["taxed" if tax else "untaxed"]
		if row.is_return:
			line["adjustment"] += flt(row.base_net_total)
			line["vat_adjustment"] += tax
		else:
			line["amount"] += flt(row.base_net_total)
			line["vat"] += tax
	return totals


def _vat_by_invoice(doctype: str, child: str, names: list[str], accounts: set[str]) -> dict[str, float]:
	"""The VAT on each invoice, from its tax rows on the VAT accounts."""
	if not accounts:
		return {}

	tax = frappe.qb.DocType(child)
	purchase = child.startswith("Purchase")
	query = (
		frappe.qb.from_(tax)
		.select(tax.parent, Sum(tax.base_tax_amount_after_discount_amount))
		.where(tax.parenttype == doctype)
		.where(tax.parent.isin(names))
		.where(tax.account_head.isin(list(accounts)))
		.groupby(tax.parent)
	)
	if not purchase:
		return {parent: flt(amount, 2) for parent, amount in query.run()}

	# A tax booked to the item's value is a cost the buyer bears, not input VAT
	# it can claim back; and a deducted one comes off.
	query = query.where(tax.category != "Valuation")
	added = dict(query.where(tax.add_deduct_tax == "Add").run())
	taken = dict(query.where(tax.add_deduct_tax == "Deduct").run())
	return {name: flt(flt(added.get(name)) - flt(taken.get(name)), 2) for name in set(added) | set(taken)}


def _rows(sales: dict, purchases: dict) -> list[dict]:
	def box(number, label, figures=None, note=None, bold=False) -> dict:
		figures = figures or {}
		return {
			"box": number,
			"description": label,
			"amount": flt(figures.get("amount"), 2),
			"adjustment": flt(figures.get("adjustment"), 2),
			"vat": flt(flt(figures.get("vat")) + flt(figures.get("vat_adjustment")), 2),
			"note": note,
			"bold": bold,
		}

	def total(*lines) -> dict:
		return {
			key: sum(flt(line[key]) for line in lines)
			for key in ("amount", "adjustment", "vat", "vat_adjustment")
		}

	not_here = _("Not held in this system — enter it yourself if it applies.")
	no_vat = _(
		"Sales with no VAT: zero-rated or exempt — the books cannot tell which. Check them and move any exempt amount to box 5."
	)
	no_vat_bought = _(
		"Purchases with no VAT: zero-rated or exempt — check them and move any exempt amount to box 11."
	)

	sold = total(sales["taxed"], sales["untaxed"])
	bought = total(purchases["taxed"], purchases["untaxed"])
	due = flt(sold["vat"] + sold["vat_adjustment"]) - flt(bought["vat"] + bought["vat_adjustment"])

	return [
		box("1", _("Standard rated sales"), sales["taxed"]),
		box("2", _("Private healthcare, private education and first home sales to citizens"), note=not_here),
		box(
			"3",
			_("Zero rated domestic sales"),
			sales["untaxed"],
			note=no_vat if sales["untaxed"]["amount"] else None,
		),
		box("4", _("Exports"), note=not_here),
		box("5", _("Exempt sales"), note=_("See box 3.")),
		box("6", _("Total sales"), sold, bold=True),
		box("7", _("Standard rated domestic purchases"), purchases["taxed"]),
		box("8", _("Imports subject to VAT paid at customs"), note=not_here),
		box(
			"9", _("Imports subject to VAT accounted for through the reverse charge mechanism"), note=not_here
		),
		box(
			"10",
			_("Zero rated purchases"),
			purchases["untaxed"],
			note=no_vat_bought if purchases["untaxed"]["amount"] else None,
		),
		box("11", _("Exempt purchases"), note=_("See box 10.")),
		box("12", _("Total purchases"), bought, bold=True),
		{**box("13", _("Total VAT due for the current period")), "vat": flt(due, 2), "bold": True},
		box("14", _("Corrections from previous period (between SAR ±5,000)"), note=not_here),
		box("15", _("VAT credit carried forward from previous period(s)"), note=not_here),
	]


def _books(company: str, from_date: str, to_date: str, accounts: set[str], rows: list[dict]) -> dict:
	"""What the VAT accounts moved by in the ledger — box 13 has to match it."""
	moved = 0.0
	if accounts:
		for entry in frappe.get_all(
			"GL Entry",
			filters={
				"company": company,
				"account": ("in", list(accounts)),
				"is_cancelled": 0,
				"posting_date": ("between", [from_date, to_date]),
			},
			fields=["debit", "credit"],
		):
			moved += flt(entry.credit) - flt(entry.debit)

	due = next(row["vat"] for row in rows if row["box"] == "13")
	agrees = abs(flt(moved, 2) - flt(due, 2)) < 0.01
	return {
		"box": "",
		"description": _("VAT accounts in the books for this period"),
		"amount": None,
		"adjustment": None,
		"vat": flt(moved, 2),
		"note": _("Agrees with box 13.")
		if agrees
		else _(
			"Differs from box 13 — look for a journal entry on a VAT account, or a document outside these invoices."
		),
		"bold": False,
	}


def _columns() -> list[dict]:
	return [
		{"fieldname": "box", "label": _("Box"), "fieldtype": "Data", "width": 60},
		{"fieldname": "description", "label": _("Description"), "fieldtype": "Data", "width": 380},
		{"fieldname": "amount", "label": _("Amount (SAR)"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "adjustment", "label": _("Adjustment (SAR)"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "vat", "label": _("VAT Amount (SAR)"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "note", "label": _("Note"), "fieldtype": "Data", "width": 360},
	]

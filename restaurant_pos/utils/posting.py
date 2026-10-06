# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Posting the till's sales to the accounts and the stock ledger (`D-313`).

A till sale is a `POS Invoice`: the tax document, the recipe as it stood, the
payment — and nothing in the general ledger or the stock ledger (`D-308`). This
takes it there, **one branch and one calendar date at a time**:

    POS Invoices of the date  ->  claimed by a `POS Posting Batch`
        accounts:  one Sales Invoice for the sales, one for the returns
        stock:     one Stock Entry for what the kitchen used, one for what came back

What the measurements on the rehearsal site made into rules (`docs/14`):

* **By date, not by day at the till.** A service that runs past midnight posts
  on two dates, or its revenue and VAT land in the wrong period (§6.4).
* **Claimed first.** The invoices are stamped with the batch under a lock, so a
  sale rung up meanwhile waits for the next one and two workers never share one.
* **Two steps, each whole or not at all.** Revenue does not wait for the stock
  ledger; a step that fails leaves nothing behind and is tried again.
* **Sums, never recomputed.** VAT is the sum of the invoices' VAT, and the few
  halalas by which those sums miss what was paid are rounding, said so (§5.2).
* **The recipe is read off the bill.** A recipe changed since the sale changes
  nothing that was sold (§4.2).

Refs: `docs/14_POS_Posting_Design.md`
"""

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import cint, flt, getdate, now_datetime, nowdate, nowtime

from restaurant_pos.utils.permissions import server_rights
from restaurant_pos.utils.sale_doc import LINE_COST, POSTED_ENTRY, SALE, SALE_ITEM

BATCH = "POS Posting Batch"

#: A step in either of these states is finished and is not run again.
DONE = ("Posted", "Nothing To Post")

SAVEPOINT = "rpos_posting_step"


def post_branch(branch: str, shift: str | None = None) -> list[str]:
	"""Post every sale of ``branch`` that is not posted yet. Returns the batches it ran.

	Batches left unfinished by an earlier run are finished first, oldest date
	first: a day's stock is not taken before the day before it (`docs/14` §7.1).
	"""
	for date in _unclaimed_dates(branch):
		_claim(branch, date, shift)

	batches = frappe.get_all(
		BATCH,
		filters={"branch": branch, "status": ("!=", "Posted")},
		pluck="name",
		order_by="posting_date asc, creation asc",
	)
	for name in batches:
		run(name)
	return batches


def run(batch_name: str):
	"""Post one batch — or what is left of it. Safe to call again and again."""
	batch = frappe.get_doc(BATCH, batch_name, for_update=True)
	if batch.status == "Posted":
		return batch

	batch.attempts = cint(batch.attempts) + 1
	errors = []

	for field, step in (("accounting_status", _post_accounts), ("stock_status", _post_stock)):
		if batch.get(field) in DONE:
			continue

		frappe.db.savepoint(SAVEPOINT)
		try:
			with server_rights():
				made = step(batch)
		except Exception as error:
			frappe.db.rollback(save_point=SAVEPOINT)
			frappe.clear_messages()
			batch.set(field, "Failed")
			errors.append(_reason(error))
			# Title only, so the traceback is the message (`D-271`).
			frappe.log_error(title=f"RPOS posting failed: {batch.name} {field}")
			continue

		batch.update(made)

	finished = batch.accounting_status in DONE and batch.stock_status in DONE
	batch.status = "Posted" if finished else "Failed"
	batch.error = "\n".join(errors) or None
	if finished:
		batch.posted_at = now_datetime()

	batch.flags.ignore_permissions = True
	batch.save()
	return batch


def stock_voucher_of(invoice: str) -> str | None:
	"""The stock document that carries what ``invoice`` moved, once it is posted.

	A sale's ingredients are on its batch's issue; what a credit note brought
	back is on its batch's receipt. None while the invoice is not posted, or
	when nothing on it is kept in stock.
	"""
	batch, is_return = frappe.db.get_value(SALE, invoice, ["rpos_posting_batch", "is_return"]) or (None, 0)
	if not batch:
		return None
	return frappe.db.get_value(BATCH, batch, "stock_receipt" if cint(is_return) else "stock_issue")


# --------------------------------------------------------------------------- #
# Claiming
# --------------------------------------------------------------------------- #


def _unposted(branch: str):
	invoice = frappe.qb.DocType(SALE)
	return invoice, (
		(invoice.rpos_branch == branch)
		& (invoice.docstatus == 1)
		& (invoice.rpos_posting_batch.isnull() | (invoice.rpos_posting_batch == ""))
	)


def _unclaimed_dates(branch: str) -> list:
	invoice, unposted = _unposted(branch)
	rows = frappe.qb.from_(invoice).select(invoice.posting_date).distinct().where(unposted).run()
	return sorted(row[0] for row in rows)


def _claim(branch: str, date, shift: str | None) -> str | None:
	"""Stamp the unposted invoices of one date with a new batch. None when there are none."""
	invoice, unposted = _unposted(branch)
	names = (
		frappe.qb.from_(invoice)
		.select(invoice.name)
		.where(unposted & (invoice.posting_date == date))
		.for_update()
		.run(pluck=True)
	)
	if not names:
		return None

	batch = frappe.get_doc(
		{
			"doctype": BATCH,
			"branch": branch,
			"posting_date": date,
			"company": frappe.db.get_value("Branch", branch, "company"),
			"restaurant_shift": shift,
			"status": "Claimed",
			"invoices": len(names),
		}
	)
	batch.flags.ignore_permissions = True
	batch.insert()

	frappe.qb.update(invoice).set(invoice.rpos_posting_batch, batch.name).where(
		invoice.name.isin(names)
	).run()
	return batch.name


def _invoices(batch) -> list[frappe._dict]:
	return frappe.get_all(
		SALE,
		filters={"rpos_posting_batch": batch.name, "docstatus": 1},
		fields=["name", "is_return", "pos_profile", "rounded_total", "grand_total"],
		order_by="posting_time asc, creation asc",
	)


# --------------------------------------------------------------------------- #
# Accounts
# --------------------------------------------------------------------------- #


def _post_accounts(batch) -> dict:
	rows = _invoices(batch)
	if not rows:
		return {"accounting_status": "Nothing To Post"}

	made = {"accounting_status": "Posted"}
	# **Sales and returns are two documents, always** (`docs/14` §8): a day with
	# only a refund is then an ordinary credit note, not a negative invoice.
	for is_return, field in ((0, "sales_invoice"), (1, "credit_note")):
		group = [row for row in rows if cint(row.is_return) == is_return]
		if not group:
			continue

		entry = _aggregate(batch, group, is_return)
		made[field] = entry
		frappe.db.set_value(
			SALE,
			{"name": ("in", [row.name for row in group])},
			{"consolidated_invoice": entry, "status": "Consolidated"},
			update_modified=False,
		)
	return made


def _aggregate(batch, rows: list, is_return: int) -> str:
	"""One Sales Invoice for ``rows``: every amount on it is the sum of theirs."""
	names = [row.name for row in rows]
	profile = frappe.get_cached_doc("POS Profile", rows[0].pos_profile)

	revenue = {}
	for line in frappe.get_all(
		SALE_ITEM,
		filters={"parent": ("in", names), "parenttype": SALE},
		fields=[
			"item_code",
			"net_rate",
			"qty",
			"net_amount",
			"income_account",
			"cost_center",
			"item_tax_template",
			"item_tax_rate",
		],
	):
		# A line keeps its VAT category: two rates are never one line, or the
		# return's boxes are wrong (`docs/14` §6.4).
		key = (
			line.item_code,
			flt(line.net_rate, 6),
			line.item_tax_template,
			line.income_account,
			line.cost_center,
		)
		row = revenue.setdefault(key, frappe._dict(qty=0.0, amount=0.0, line=line))
		row.qty += flt(line.qty)
		row.amount += flt(line.net_amount)

	taxes = {}
	for tax in frappe.get_all(
		"Sales Taxes and Charges",
		filters={"parent": ("in", names), "parenttype": SALE},
		fields=["account_head", "cost_center", "description", "tax_amount_after_discount_amount"],
	):
		row = taxes.setdefault((tax.account_head, tax.cost_center), frappe._dict(tax, amount=0.0))
		row.amount += flt(tax.tax_amount_after_discount_amount)

	paid = {}
	for payment in frappe.get_all(
		"Sales Invoice Payment",
		filters={"parent": ("in", names), "parenttype": SALE},
		fields=["mode_of_payment", "amount"],
	):
		paid[payment.mode_of_payment] = paid.get(payment.mode_of_payment, 0.0) + flt(payment.amount)

	# What the customers paid against, and what the lines and taxes add up to.
	# Each invoice rounds its own net and tax, so the sums drift by a few
	# halalas: that drift is rounding, and it is said so — left unsaid, ERPNext
	# writes it off as money never collected (`docs/14` §5.2).
	rounded = flt(sum(flt(row.rounded_total) or flt(row.grand_total) for row in rows), 2)
	rounding = flt(
		rounded - sum(row.amount for row in revenue.values()) - sum(row.amount for row in taxes.values()), 2
	)

	date = getdate(batch.posting_date)
	entry = frappe.get_doc(
		{
			"doctype": POSTED_ENTRY,
			"company": batch.company,
			"customer": profile.customer,
			"pos_profile": profile.name,
			"currency": profile.currency,
			"selling_price_list": profile.selling_price_list,
			"is_pos": 1,
			"is_return": is_return,
			# ERPNext takes a consolidated invoice at its word — no line is
			# recomputed — and its ZATCA integration does not report it: the
			# POS Invoices are the tax documents.
			"is_consolidated": 1,
			"update_stock": 0,
			"ignore_pricing_rule": 1,
			"set_posting_time": 1,
			"posting_date": date,
			"posting_time": _time_on(date),
			"due_date": date,
			"rpos_posting_batch": batch.name,
			"remarks": _remark(batch),
			**(
				{
					"rounding_adjustment": rounding,
					"base_rounding_adjustment": rounding,
					"rounded_total": rounded,
					"base_rounded_total": rounded,
				}
				if rounding
				else {}
			),
			"items": [
				{
					"item_code": item_code,
					"qty": row.qty,
					"rate": rate,
					"net_rate": rate,
					"base_rate": rate,
					"base_net_rate": rate,
					"amount": row.amount,
					"net_amount": row.amount,
					"base_amount": row.amount,
					"base_net_amount": row.amount,
					"conversion_factor": 1,
					"income_account": income_account,
					"cost_center": cost_center,
					"item_tax_template": template,
					"item_tax_rate": row.line.item_tax_rate,
				}
				for (item_code, rate, template, income_account, cost_center), row in revenue.items()
				if row.qty
			],
			"taxes": [
				{
					"charge_type": "Actual",
					"account_head": row.account_head,
					"cost_center": row.cost_center,
					"description": row.description,
					"tax_amount": row.amount,
				}
				for row in taxes.values()
			],
			"payments": [{"mode_of_payment": method, "amount": amount} for method, amount in paid.items()],
		}
	)
	entry.flags.ignore_permissions = True
	entry.insert()
	entry.submit()
	return entry.name


# --------------------------------------------------------------------------- #
# Stock
# --------------------------------------------------------------------------- #


def _post_stock(batch) -> dict:
	earlier = frappe.get_all(
		BATCH,
		filters={
			"branch": batch.branch,
			"posting_date": ("<", batch.posting_date),
			"stock_status": ("not in", DONE),
		},
		pluck="name",
		limit=1,
	)
	if earlier:
		frappe.throw(
			_(
				"The stock of {0} is not posted yet, and a day's stock is taken after the day before it."
			).format(earlier[0])
		)

	rows = _invoices(batch)
	_stamp_standard_costs(batch)
	sold = _moved([row.name for row in rows if not cint(row.is_return)])
	back = _moved([row.name for row in rows if cint(row.is_return)])
	if not sold and not back:
		return {"stock_status": "Nothing To Post"}

	_assert_priced(sold, batch)

	made = {"stock_status": "Posted"}
	if sold:
		made["stock_issue"] = _stock_entry(batch, "Material Issue", sold)
		_stamp_costs(batch, made["stock_issue"], is_return=0)
	if back:
		made["stock_receipt"] = _stock_entry(batch, "Material Receipt", back)
		_stamp_costs(batch, made["stock_receipt"], is_return=1)
	return made


def _invoices_in(batch, is_return: int | None = None):
	"""The batch's invoices, as a subquery — a day's bills are too many to list by name."""
	invoice = frappe.qb.DocType(SALE)
	of_batch = invoice.rpos_posting_batch == batch.name
	return (
		frappe.qb.from_(invoice)
		.select(invoice.name)
		.where(of_batch if is_return is None else of_batch & (invoice.is_return == is_return))
	)


def _stamp_standard_costs(batch) -> None:
	"""A dish kept without stock and without a recipe costs what its item card says (`D-314`).

	That is the whole cost model of a restaurant that keeps no stock: a
	Valuation Rate typed on the dish. ERPNext read it onto every Sales Invoice
	line; a POS Invoice line has nowhere to carry it until this writes it.
	"""
	line = frappe.qb.DocType(SALE_ITEM)
	in_batch = _invoices_in(batch)
	sold = (
		frappe.qb.from_(line)
		.select(line.item_code)
		.distinct()
		.where(line.parent.isin(in_batch) & (line.parenttype == SALE))
		.run(pluck=True)
	)
	if not sold:
		return

	recipes = set(
		frappe.get_all("Product Bundle", filters={"new_item_code": ("in", sold)}, pluck="new_item_code")
	)
	for item in frappe.get_all(
		"Item",
		filters={"name": ("in", sold), "is_stock_item": 0, "valuation_rate": (">", 0)},
		fields=["name", "valuation_rate"],
	):
		if item.name in recipes:
			# Its ingredients carry the cost, each on its own recipe row.
			continue
		(
			frappe.qb.update(line)
			.set(line[LINE_COST], flt(item.valuation_rate))
			.where(line.parent.isin(in_batch) & (line.parenttype == SALE) & (line.item_code == item.name))
			.run()
		)


def _stamp_costs(batch, stock_entry: str, *, is_return: int) -> None:
	"""Write what each item cost onto the bills that sold it (`D-314`).

	The stock ledger knows the cost of the day's cheese; it does not know which
	bill sold which slice, and a POS Invoice has no ledger of its own. So the
	rate the ledger used is written back onto the lines and recipe rows of the
	batch's invoices — once, when the stock is taken — and a report reads a
	sale's cost off the sale, as it did when every sale posted itself.

	**A fact about the day it was posted, not a live figure.** A purchase keyed
	later with an older date makes ERPNext re-value the issue in the ledger; the
	rate stamped here stays what it was.
	"""
	ledger = frappe.qb.DocType("Stock Ledger Entry")
	in_batch = _invoices_in(batch, is_return)

	for item, warehouse, qty, value in (
		frappe.qb.from_(ledger)
		.select(
			ledger.item_code, ledger.warehouse, Sum(ledger.actual_qty), Sum(ledger.stock_value_difference)
		)
		.where((ledger.voucher_no == stock_entry) & (ledger.is_cancelled == 0))
		.groupby(ledger.item_code, ledger.warehouse)
		.run()
	):
		rate = abs(flt(value) / flt(qty)) if flt(qty) else 0.0
		for doctype, field in ((SALE_ITEM, LINE_COST), ("Packed Item", "incoming_rate")):
			row = frappe.qb.DocType(doctype)
			(
				frappe.qb.update(row)
				.set(row[field], rate)
				.where(
					row.parent.isin(in_batch)
					& (row.parenttype == SALE)
					& (row.item_code == item)
					& (row.warehouse == warehouse)
				)
				.run()
			)


def _moved(invoices: list[str]) -> dict[tuple[str, str], float]:
	"""(item, warehouse) -> quantity, read off the bills: their stock lines and their recipe rows."""
	if not invoices:
		return {}

	moved: dict[tuple[str, str], float] = {}
	rows = frappe.get_all(
		SALE_ITEM,
		filters={"parent": ("in", invoices), "parenttype": SALE},
		fields=["item_code", "warehouse", "stock_qty as qty"],
	) + frappe.get_all(
		"Packed Item",
		filters={"parent": ("in", invoices), "parenttype": SALE},
		fields=["item_code", "warehouse", "qty"],
	)
	stocked = set(
		frappe.get_all(
			"Item",
			filters={"name": ("in", list({row.item_code for row in rows})), "is_stock_item": 1},
			pluck="name",
		)
	)
	for row in rows:
		# An item kept without stock moves nothing: a restaurant that keeps no
		# stock at all posts its accounts and no stock entry (`docs/14` §5.2).
		if row.item_code in stocked and flt(row.qty):
			key = (row.item_code, row.warehouse)
			moved[key] = moved.get(key, 0.0) + abs(flt(row.qty))
	return moved


def _assert_priced(sold: dict, batch) -> None:
	"""Refuse to start while an ingredient has no cost — rather than fail half way."""
	from erpnext.stock.stock_ledger import get_valuation_rate

	unpriced = sorted(
		item
		for item, warehouse in sold
		if not flt(
			# The voucher is "any but this one"; a name no document has, because a
			# null there matches nothing at all and every item reads as unpriced.
			get_valuation_rate(
				item,
				warehouse,
				"Stock Entry",
				batch.name,
				company=batch.company,
				raise_error_if_no_rate=False,
			)
		)
	)
	if unpriced:
		frappe.throw(
			_(
				"These items have no cost yet, so what was sold of them cannot be valued: {0}. "
				"Enter a purchase for each, or a Valuation Rate on its item card, then post again."
			).format(", ".join(unpriced))
		)


def _stock_entry(batch, purpose: str, moved: dict) -> str:
	date = getdate(batch.posting_date)
	issue = purpose == "Material Issue"
	rows = []
	for (item, warehouse), qty in sorted(moved.items()):
		row = {"item_code": item, "qty": qty, "expense_account": _cost_account(item, batch.company)}
		row["s_warehouse" if issue else "t_warehouse"] = warehouse
		if not issue:
			# What comes back comes back at what the shelf is worth today, as
			# ERPNext values a return of a moving-average item (`docs/14` §8.1).
			row["basic_rate"] = flt(
				frappe.db.get_value("Bin", {"item_code": item, "warehouse": warehouse}, "valuation_rate")
			)
		rows.append(row)

	entry = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": purpose,
			"company": batch.company,
			"set_posting_time": 1,
			"posting_date": date,
			"posting_time": _time_on(date),
			"rpos_posting_batch": batch.name,
			"remarks": _remark(batch),
			"items": rows,
		}
	)
	entry.flags.ignore_permissions = True
	entry.insert()
	entry.submit()
	return entry.name


def _cost_account(item: str, company: str) -> str:
	"""Where an item's cost of sales goes: its own default, else the company's."""
	return frappe.db.get_value(
		"Item Default", {"parent": item, "company": company}, "expense_account"
	) or frappe.get_cached_value("Company", company, "default_expense_account")


# --------------------------------------------------------------------------- #


def _time_on(date) -> str:
	"""The end of a day that is over; now, for a day still running — never a moment yet to come."""
	return nowtime() if getdate(date) >= getdate(nowdate()) else "23:59:59"


def _remark(batch) -> str:
	day = f" | {_('POS Day')}: {batch.restaurant_shift}" if batch.restaurant_shift else ""
	return _("Till sales of {0} on {1} — {2}").format(batch.branch, batch.posting_date, batch.name) + day


def _reason(error: Exception) -> str:
	return frappe.utils.strip_html(str(error) or type(error).__name__)[:500]

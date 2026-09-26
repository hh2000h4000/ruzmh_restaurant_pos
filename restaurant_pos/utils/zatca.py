# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The ZATCA Phase 1 QR code — the one every simplified invoice must carry.

**Phase 1 (Generation) and Phase 2 (Integration) are different problems**, and
only the second needs an integration app (`D-092`):

* **Phase 1** — a QR on the printed receipt holding five fields. Local
  arithmetic and a bitmap; no network, no keys, no registration. Mandatory on
  every simplified tax invoice in Saudi Arabia. **This module.**
* **Phase 2** — clearing and reporting invoices to ZATCA's Fatoora platform:
  signed XML, cryptographic stamps, a CSID obtained by onboarding. That is what
  Lavaloon's app (or an equivalent) exists to do, and it is Phase 5 here.

The QR is a **TLV** sequence — tag, length, value — base64 encoded:

    1 seller name · 2 VAT number · 3 timestamp · 4 total with VAT · 5 VAT amount

Refs: FR-7.5, D-092
"""

from __future__ import annotations

import base64
from datetime import datetime

import frappe
from frappe.utils import flt, get_datetime, get_system_timezone

from restaurant_pos.utils.barcodes import qr_data_uri

#: Tag numbers, in the order ZATCA specifies. The order is part of the format.
SELLER_NAME = 1
VAT_NUMBER = 2
TIMESTAMP = 3
INVOICE_TOTAL = 4
VAT_TOTAL = 5

#: A TLV length is one byte, so no value may exceed 255 **bytes**. Arabic is
#: two bytes a letter in UTF-8, which halves how long a seller name may be.
MAX_VALUE_BYTES = 255


def tlv(tag: int, value: str) -> bytes:
	"""One tag-length-value triple.

	The length counts **bytes, not characters**. Getting that wrong produces a
	QR that scans perfectly for an English seller name and is corrupt for an
	Arabic one — which is every restaurant this is for.
	"""
	encoded = value.encode("utf-8")
	if len(encoded) > MAX_VALUE_BYTES:
		# Cutting at a byte offset lands mid-character in Arabic, and the leftover
		# lead byte is not valid UTF-8 — a scanner decoding the payload gets an
		# error rather than a name. Decoding with `ignore` drops exactly the
		# partial character, whether what remains is a lead byte or a
		# continuation one; an earlier version only handled the latter and this
		# test caught it.
		encoded = encoded[:MAX_VALUE_BYTES].decode("utf-8", "ignore").encode("utf-8")

	return bytes([tag, len(encoded)]) + encoded


def qr_payload(
	*,
	seller_name: str,
	vat_number: str,
	timestamp: datetime,
	invoice_total: float,
	vat_total: float,
) -> str:
	"""The five fields, TLV encoded and base64'd — what the QR actually holds."""
	fields = (
		(SELLER_NAME, seller_name or ""),
		(VAT_NUMBER, vat_number or ""),
		(TIMESTAMP, _iso_utc(timestamp)),
		(INVOICE_TOTAL, f"{flt(invoice_total, 2):.2f}"),
		(VAT_TOTAL, f"{flt(vat_total, 2):.2f}"),
	)

	return base64.b64encode(b"".join(tlv(tag, value) for tag, value in fields)).decode("ascii")


def _iso_utc(moment: datetime) -> str:
	"""ISO 8601 in UTC, as the specification asks.

	A Frappe timestamp is naive and in the site's timezone, so it is converted
	rather than stamped with a Z it has not earned — a receipt an hour out is a
	receipt whose QR disagrees with its own printed time.
	"""
	import pytz

	if moment.tzinfo is None:
		moment = pytz.timezone(get_system_timezone()).localize(moment)

	return moment.astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


#: The ZATCA integration, when the restaurant has one installed.
INTEGRATION = "ksa_compliance"


def invoice_qr(invoice) -> str | None:
	"""The QR for one Sales Invoice, ready to drop into an `<img src>`.

	**One decision, in one place** (`D-154`). The till's receipt and the copy an
	accountant prints both come through here, so they cannot show different
	codes for the same sale — which is precisely what two generators side by
	side would eventually do.

	The integration wins whenever it has an answer, because **phase two is not a
	specification we can satisfy**: its QR carries a cryptographic stamp issued
	after the invoice is signed and cleared. Ours is the fallback for a site
	that has not installed one, and for a phase-1 setting that is switched off —
	a simplified tax invoice needs its code either way.

	Returns None when the company has no VAT number: a QR missing tag 2 is not
	a lenient QR, it is an invalid one, and printing it would look like
	compliance while being the opposite.
	"""
	delegated = integration_qr(invoice)
	if delegated:
		return delegated

	company = frappe.get_cached_doc("Company", invoice.company)
	if not company.tax_id:
		return None

	posting = get_datetime(f"{invoice.posting_date} {invoice.posting_time or '00:00:00'}")

	payload = qr_payload(
		seller_name=company.company_name or company.name,
		vat_number=company.tax_id,
		timestamp=posting,
		invoice_total=flt(invoice.rounded_total or invoice.grand_total),
		vat_total=flt(invoice.total_taxes_and_charges),
	)

	return qr_data_uri(payload)


def integration_qr(invoice) -> str | None:
	"""What the ZATCA app says this invoice's QR is, if it says anything.

	**Phase two first.** Once an invoice has been cleared, its QR is the stamped
	one on `Sales Invoice Additional Fields` — the phase-one code for the same
	invoice would be a valid-looking QR that is no longer the right one.

	Never raises. A print is not the place to discover that an integration is
	misconfigured: the receipt still has to come out, and the failure belongs in
	the error log where somebody can read it (`D-084`, the same rule the print
	agent follows).
	"""
	if INTEGRATION not in frappe.get_installed_apps():
		return None

	stamped = _tried("phase two", lambda: _stamped_qr(invoice))
	if stamped:
		return stamped

	encoded = _tried("phase one", lambda: _phase_one_qr(invoice))
	# Their phase-one helper answers with bare base64; ours is handed straight
	# to an `<img src>`.
	return f"data:image/png;base64,{encoded}" if encoded else None


def _tried(what: str, work):
	"""Run one attempt, and let a broken one not take the others with it.

	**Each link is tried on its own.** The first version wrapped both in one
	`try`, and the phase-two lookup raising on a column the app had not migrated
	yet swallowed the phase-one answer that was sitting right there — the paper
	came out with our own code while an integration was installed and working.
	Measured on the demo site the day the app went in.
	"""
	try:
		return work()
	except Exception:
		# **Title only, so the traceback is the message** (`D-271`). The second
		# argument used to be «RPOS zatca», which Frappe takes as the message in
		# place of the traceback: 55 entries on the user's site said a ZATCA
		# failure and not one said which — it was our own query, below.
		frappe.log_error(title=f"ZATCA integration failed at {what}")
		return None


def _stamped_qr(invoice) -> str | None:
	"""The cleared invoice's own QR, stamped by ZATCA (phase two).

	**Read off the document, not the table** (`D-271`). `qr_image_src` is a
	Python property that draws `qr_code` as a PNG when asked; it has no column,
	and selecting it failed on every print of every invoice on a site with the
	app installed. An invoice the app has not processed has no record at all,
	and that is simply no stamped QR — not a failure.
	"""
	name = frappe.db.get_value(
		"Sales Invoice Additional Fields",
		{"sales_invoice": invoice.name},
		"name",
		order_by="creation desc",
	)
	if not name:
		return None
	return frappe.get_doc("Sales Invoice Additional Fields", name).qr_image_src


def _phase_one_qr(invoice) -> str | None:
	from ksa_compliance.jinja import get_zatca_phase_1_qr_for_invoice

	return get_zatca_phase_1_qr_for_invoice(invoice.name)


def rpos_invoice_qr(invoice) -> str | None:
	"""What a print format calls, and the only reason it is not `invoice_qr`.

	Jinja globals are **one namespace shared by every installed app**, and the
	app most likely to register something called `invoice_qr` is a ZATCA
	integration — which is exactly the app we plan to trial (`D-153`). A
	collision there would be silent: one of the two wins and the other's QR
	simply stops appearing.
	"""
	return invoice_qr(invoice)

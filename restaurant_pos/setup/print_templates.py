# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The templates a restaurant prints with before anybody edits one.

Shipped rather than left to setup because the alternative is a POS that cannot
print on the day it is installed, and a first receipt designed under pressure.

One HTML source per document type, instantiated once per paper width. The only
thing that differs between widths is the root font size: wkhtmltoimage renders
at the paper's dot width, so a size that fills 80mm correctly overflows 58mm.
Everything else is in `rem`, and follows.

Refs: FR-7.2, FR-7.4, FR-7.5, D-084
"""

import frappe
from frappe.utils import time_diff_in_seconds

#: Root font size in px per paper width, so `rem` means the same physical size
#: on every roll. 80mm prints 576 dots, 58mm prints 384 — two thirds of it.
#: 11px on 58mm paper fitted about seventy characters to a line, which is denser
#: than any receipt a customer is handed and was reported as simply too small to
#: read. Long item names wrap sooner now, which is the right trade.
ROOT_PX = {
	"58mm": 13,
	"76mm": 14,
	"80mm": 16,
}

#: Shared by every template. Arabic first in the stack, then whatever the server
#: has: if the box is missing an Arabic face the receipt still renders, it just
#: renders plainly — which is a better failure than a page of empty boxes.
BASE_CSS = """
@page { margin: 0; }
* { box-sizing: border-box; }
/* Nothing may make the page wider than the paper.
 *
 * In an RTL page, text starts at the *right* edge — so a single long token that
 * stretches the body pushes the start of every line off the roll, and the
 * ticket prints with the item names sheared off. That is what a real kitchen
 * ticket did: one long table id widened the page and took the food with it.
 * `hidden` alone would not do it; the long token has to be allowed to break. */
html, body { width: 100%; max-width: 100%; overflow-x: hidden; }
* { overflow-wrap: anywhere; }
body {
	margin: 0; padding: 0.5rem;
	font-family: "Noto Naskh Arabic", "Amiri", "Segoe UI", "DejaVu Sans", sans-serif;
	font-size: 1rem; line-height: 1.35; color: #000; background: #fff;
	-webkit-font-smoothing: none;
}
.c { text-align: center; }
.rtl { direction: rtl; }
.big { font-size: 1.5rem; font-weight: bold; }
.huge { font-size: 2.2rem; font-weight: bold; }
.muted { font-size: 0.8rem; }
hr { border: 0; border-top: 1px dashed #000; margin: 0.4rem 0; }
/* Columns are flex rows, not a `<table>` — measured, not preferred (`D-090`).
 *
 * wkhtmltoimage mangles Arabic containing digits inside a table cell and
 * **nothing fixes it there**: an RLM, an RLE/PDF pair and a `dir` attribute
 * were each tried, and the RLM makes even plain Arabic worse. The same text in
 * a flex row, marked by the `rtl` filter, renders correctly. "برغر لحم 200
 * جرام" is an ordinary menu item, so a receipt that cannot print it is not a
 * receipt. */
.line { display: flex; gap: 0.4rem; align-items: baseline; font-size: 0.95rem; padding: 0.1rem 0; }
.line .name { flex: 1 1 auto; min-width: 0; }
.line .col { flex: 0 0 4.2rem; text-align: end; direction: ltr; unicode-bidi: isolate; }
/* The header keeps the data columns' direction, or `text-align: end` means the
 * opposite edge for the label and for the figure under it, and nothing lines
 * up. Each heading is a single Arabic run, so an LTR box lays it out correctly. */
.line.head { border-bottom: 1px solid #000; font-weight: bold; }
.num { text-align: end; white-space: nowrap; }
/* Every printed number is isolated from the Arabic around it.
 *
 * Without this, "10.00 ر.س" inside an RTL line is handed to the bidi algorithm
 * as one run, and the currency ends up wrapped into the digits — the total line
 * came out unreadable on the first real receipt. `isolate` is what says "this
 * span is a self-contained LTR run", which is exactly what an amount is. */
.num, .amt { direction: ltr; unicode-bidi: isolate; }
.row { display: flex; justify-content: space-between; gap: 0.5rem; }
/* A flex item's `min-width` defaults to `auto`, which means it refuses to
 * shrink below its own text and overflows the row instead of wrapping. On an
 * RTL line the overflow runs off the start edge, so the *beginning* of the
 * label is what disappears: "ضريبة القيمة المضافة 15%" printed as "ة 15%".
 * `min-width: 0` is what lets `overflow-wrap` above actually do its job. */
.row > * { min-width: 0; }
.row > .num, .row > .amt { flex: none; }
.total { font-size: 1.3rem; font-weight: bold; }
.b { font-weight: bold; }
/* A bilingual row: English label, the figure, Arabic label.
 *
 * The container is LTR so the source reads in the order it prints, and each
 * cell carries its own direction and isolation. That is the whole trick: a date
 * or an amount in its own isolated LTR box cannot be reordered into the Arabic
 * label beside it, which is the failure this project keeps meeting. */
.tri { display: flex; direction: ltr; gap: 0.3rem; align-items: baseline; padding: 0.08rem 0; }
.tri > .en { flex: 0 0 30%; text-align: left; unicode-bidi: isolate; }
.tri > .val { flex: 1 1 auto; min-width: 0; text-align: center; }
.tri > .ar { flex: 0 0 32%; text-align: right; direction: rtl; unicode-bidi: isolate; }
.rule { border-top: 1px solid #000; margin: 0.35rem 0; }
/* The one line a customer checks before walking away, so it is the one thing on
 * the receipt that is unmistakable at arm's length. */
.pay { border-top: 2px solid #000; border-bottom: 2px solid #000;
	margin: 0.4rem 0; padding: 0.25rem 0; font-size: 1.45rem; font-weight: bold; }
.logo { max-width: 50%; }
.stars { letter-spacing: 0.08em; }
/* A kitchen ticket's modifiers and notes are not annotations — "بدون ملح" is
 * the whole instruction, and one a cook scanning a rail must not miss. Set
 * below the item name, but not so far below that it reads as small print. */
.mod { font-size: 1.15rem; padding-inline-start: 1.2rem; }
.note { font-size: 1.25rem; font-weight: bold; padding-inline-start: 1.2rem; }
"""

CUSTOMER_RECEIPT = """
<html><head><meta charset="utf-8"><style>{css}</style></head>
<body class="rtl">
	<div class="c">
		{{% if logo %}}<img class="logo" src="{{{{ logo }}}}" alt="">{{% endif %}}
		<div class="big">{{{{ (company.company_name or company.name) | rtl }}}}</div>
		{{% if branch %}}<div>{{{{ branch.branch | rtl }}}}</div>{{% endif %}}
		{{% if company.tax_id %}}<div class="muted">TAX Number: {{{{ company.tax_id }}}}</div>{{% endif %}}
	</div>
	<hr>
	{{# Two columns, not the three-column row below: a fixed 30% column wrapped
	    "Simplified Tax Invoice" onto two lines, and the heading of a receipt is
	    the last place to save space. #}}
	<div class="row b"><span>فاتورة ضريبية مبسطة</span><span>Simplified Tax Invoice</span></div>
	{{% if order.daily_number %}}
	<div class="tri">
		<span class="en huge">{{{{ order.daily_number }}}}</span>
		<span class="val"></span>
		<span class="ar big">{{{{ order.order_type_title | rtl }}}}</span>
	</div>
	{{% endif %}}
	<hr>
	<div class="tri">
		<span class="en">Date</span>
		<span class="val">{{{{ frappe.utils.formatdate(doc.posting_date) }}}} {{{{ frappe.utils.format_time(doc.posting_time) }}}}</span>
		<span class="ar">التاريخ</span>
	</div>
	<div class="tri">
		<span class="en">Cashier</span>
		<span class="val">{{{{ (order.cashier_name or doc.owner) | rtl }}}}</span>
		<span class="ar">الكاشير</span>
	</div>
	<div class="tri">
		<span class="en">Invoice</span>
		<span class="val">{{{{ doc.name }}}}</span>
		<span class="ar">رقم الفاتورة</span>
	</div>
	{{% if order.table_number %}}
	<div class="tri">
		<span class="en">Table</span>
		<span class="val">{{{{ order.table_number }}}}</span>
		<span class="ar">الطاولة</span>
	</div>
	{{% endif %}}
	<div class="rule"></div>
	<div class="line head">
		<span class="name">الصنف</span>
		<span class="col">الكمية</span><span class="col">السعر</span><span class="col">الإجمالي</span>
	</div>
	{{% for item in doc.items %}}
	<div class="line">
		<span class="name">{{{{ item.item_name | rtl }}}}</span>
		<span class="col">{{{{ item.qty | int }}}}</span>
		<span class="col">{{{{ "%.2f" | format(item.rate) }}}}</span>
		<span class="col">{{{{ "%.2f" | format(item.amount) }}}}</span>
	</div>
	{{% endfor %}}
	<div class="rule"></div>
	<div class="tri">
		<span class="en">Subtotal</span>
		<span class="val amt">{{{{ "%.2f" | format(doc.net_total) }}}}</span>
		<span class="ar">الإجمالي قبل الضريبة</span>
	</div>
	{{% if doc.discount_amount %}}
	<div class="tri">
		<span class="en">Discount</span>
		<span class="val amt">{{{{ "%.2f" | format(doc.discount_amount) }}}}</span>
		<span class="ar">الخصم</span>
	</div>
	{{% endif %}}
	{{% for tax in doc.taxes %}}
	<div class="tri">
		<span class="en">VAT {{{{ "%g" | format(tax.rate) }}}}%</span>
		<span class="val amt">{{{{ "%.2f" | format(tax.tax_amount) }}}}</span>
		<span class="ar">{{{{ tax.description | rtl }}}}</span>
	</div>
	{{% endfor %}}
	<div class="row pay">
		<span>المطلوب</span>
		<span class="amt">SAR {{{{ "%.2f" | format(doc.rounded_total or doc.grand_total) }}}}</span>
	</div>
	{{% for payment in doc.payments %}}
	<div class="row"><span>{{{{ payment.mode_of_payment | rtl }}}}</span><span class="amt">{{{{ "%.2f" | format(payment.amount) }}}}</span></div>
	{{% endfor %}}
	{{% if doc.change_amount %}}
	<div class="tri">
		<span class="en">Change</span>
		<span class="val amt">{{{{ "%.2f" | format(doc.change_amount) }}}}</span>
		<span class="ar">الباقي</span>
	</div>
	{{% endif %}}
	{{% if zatca_qr %}}
	<hr>
	{{# ZATCA Phase 1. Drawn at whole dots per module by `utils/zatca`, so it must
	    not be resized here — a scaled QR prints with grey edges on thermal paper
	    and scanners misread it. #}}
	<div class="c"><img src="{{{{ zatca_qr }}}}" alt=""></div>
	{{% endif %}}
	<hr>
	{{# One line each. "THANK YOU · شكراً لزيارتكم" printed as overlapping
	    fragments: a Latin run and an Arabic run in one line is the same shape
	    that mangles a label beside a number, and the separator between them is
	    not worth a garbled thank-you. #}}
	<div class="c muted stars">********************************</div>
	<div class="c b">THANK YOU</div>
	<div class="c b">شكراً لزيارتكم</div>
	<div class="c muted stars">********************************</div>
</body></html>
"""

BILL_PREVIEW = """
<html><head><meta charset="utf-8"><style>{css}</style></head>
<body class="rtl">
	<div class="c">
		<div class="big">{{{{ (company.company_name or company.name) | rtl }}}}</div>
		<div class="big">— غير ضريبية —</div>
		<div class="muted">للمراجعة فقط، ليست فاتورة</div>
	</div>
	<hr>
	<div class="row"><span>رقم الطلب</span><b>{{{{ doc.daily_number or doc.name }}}}</b></div>
	{{% if doc.table %}}<div class="row"><span>الطاولة</span><span>{{{{ doc.table }}}}</span></div>{{% endif %}}
	<div class="row"><span>الكاشير</span><span>{{{{ doc.cashier_name }}}}</span></div>
	<hr>
	<div class="line head">
		<span class="name">الصنف</span>
		<span class="col">الكمية</span><span class="col">الإجمالي</span>
	</div>
	{{% for item in doc.items %}}
	{{% if not item.is_void %}}
	<div class="line">
		<span class="name">{{{{ item.item_name | rtl }}}}</span>
		<span class="col">{{{{ item.qty | int }}}}</span>
		<span class="col">{{{{ "%.2f" | format(item.amount) }}}}</span>
	</div>
	{{% endif %}}
	{{% endfor %}}
	<hr>
	<div class="row total"><span>الإجمالي</span><span><span class="amt">{{{{ "%.2f" | format(totals.grand_total) }}}}</span> ر.س</span></div>
	<div class="c muted">شامل ضريبة القيمة المضافة</div>
</body></html>
"""

KOT = """
<html><head><meta charset="utf-8"><style>{css}</style></head>
<body class="rtl">
	<div class="c huge">{{{{ (doc.order_type_title or "") | rtl }}}}</div>
	<div class="c huge">#{{{{ doc.daily_number }}}}</div>
	{{% if doc.call_name %}}<div class="c big">{{{{ doc.call_name | rtl }}}}</div>{{% endif %}}
	<hr>
	<div class="row"><span>{{{{ station | rtl }}}}</span>
		<span class="amt">{{{{ frappe.utils.format_datetime(doc.sent_at, "HH:mm") }}}}</span></div>
	{{% if table_number %}}<div class="row"><span>الطاولة</span><b class="amt">{{{{ table_number }}}}</b></div>{{% endif %}}
	<div class="row muted"><span>{{{{ doc.cashier_name }}}}</span><span class="amt">{{{{ doc.name }}}}</span></div>
	{{% if doc.kot_type != "initial" %}}
	<div class="c big">
		{{% if doc.kot_type == "addition" %}}إضافة على الطلب
		{{% elif doc.kot_type == "void" %}}إلغاء أصناف
		{{% else %}}إعادة طباعة{{% endif %}}
	</div>
	{{% endif %}}
	<hr>
	{{% for item in doc.items %}}
	<div style="margin-bottom: 0.4rem;">
		{{# The quantity is its own isolated box rather than part of the sentence.
		    A quantity, a multiplication sign and an Arabic name in one run are
		    handed to the bidi algorithm mixed, and the digits land inside the
		    name. A cook reading a smeared quantity makes the wrong number of
		    plates. #}}
		<div class="big">
			<span class="amt">{{% if item.action == "void" %}}&#10005;{{% endif %}}{{{{ item.qty | int }}}}&times;</span>
			{{{{ item.item_name | rtl }}}}
		</div>
		{{% if item.modifiers %}}
		{{% for modifier in frappe.parse_json(item.modifiers) %}}
		<div class="mod">+ {{{{ (modifier.get("title") or modifier.get("item_name") or modifier) | rtl }}}}</div>
		{{% endfor %}}
		{{% endif %}}
		{{% if item.notes %}}<div class="note">{{{{ item.notes | rtl }}}}</div>{{% endif %}}
	</div>
	{{% endfor %}}
	{{% if doc.order_notes %}}
	<hr>
	<div class="big">{{{{ doc.order_notes | rtl }}}}</div>
	{{% endif %}}
</body></html>
"""

SHIFT_REPORT = """
<html><head><meta charset="utf-8"><style>{css}</style></head>
<body class="rtl">
	<div class="c big">تقرير المناوبة</div>
	<div class="c muted">{{{{ doc.pos_profile }}}}</div>
	<hr>
	<div class="row"><span>الفتح</span><span>{{{{ frappe.utils.format_datetime(doc.period_start_date) }}}}</span></div>
	<div class="row"><span>الإغلاق</span><span>{{{{ frappe.utils.format_datetime(doc.period_end_date) }}}}</span></div>
	<div class="row"><span>الكاشير</span><span>{{{{ doc.owner }}}}</span></div>
	<hr>
	<div class="line head">
		<span class="name">طريقة الدفع</span>
		<span class="col">متوقّع</span><span class="col">معدود</span><span class="col">الفرق</span>
	</div>
	{{% for row in doc.payment_reconciliation %}}
	<div class="line">
		<span class="name">{{{{ row.mode_of_payment | rtl }}}}</span>
		<span class="col">{{{{ "%.2f" | format(row.expected_amount) }}}}</span>
		<span class="col">{{{{ "%.2f" | format(row.closing_amount) }}}}</span>
		<span class="col">{{{{ "%.2f" | format(row.difference) }}}}</span>
	</div>
	{{% endfor %}}
	<hr>
	<div class="row total"><span>صافي المبيعات</span><span class="amt">{{{{ "%.2f" | format(doc.grand_total) }}}}</span></div>
	<div class="row"><span>عدد الفواتير</span><span class="amt">{{{{ doc.pos_transactions | length }}}}</span></div>
</body></html>
"""

#: Type -> (Arabic title, English title, HTML).
SOURCES = {
	"customer_receipt": ("إيصال العميل", "Customer Receipt", CUSTOMER_RECEIPT),
	"kot": ("تذكرة المطبخ", "Kitchen Ticket", KOT),
	"bill_preview": ("معاينة الفاتورة", "Bill Preview", BILL_PREVIEW),
	"shift_report": ("تقرير المناوبة", "Shift Report", SHIFT_REPORT),
}


def create_default_templates() -> None:
	"""Install one default template per type and paper width. Idempotent.

	**A template nobody has edited is refreshed; one somebody edited is never
	touched.** Both halves matter. A restaurant that redesigned its receipt must
	not find the design gone after a migrate — that is a change nobody made,
	arriving unannounced, in the thing the customer is handed. But a site that
	never opened the screen should get a fix to the shipped template, or the bug
	is frozen into every install that predates it. The first real receipt
	rendered proved that: the currency ran into the total, and without this the
	repair would have reached new sites only.

	"Edited" is `modified` having moved away from `creation`, which is why the
	refresh below writes with `update_modified=False` — a template we corrected
	is still an untouched one, and must stay eligible for the next correction.
	"""
	for template_type, (title_ar, title_en, html) in SOURCES.items():
		for paper_width, root_px in ROOT_PX.items():
			title = f"{title_en} {paper_width}"
			css = f"html {{ font-size: {root_px}px; }}" + BASE_CSS
			body = html.format(css=css).strip()

			existing = frappe.db.get_value(
				"POS Print Template", title, ["name", "creation", "modified"], as_dict=True
			)
			if existing:
				if _was_edited(existing):
					continue
				frappe.db.set_value("POS Print Template", title, "template_html", body, update_modified=False)
				continue

			frappe.get_doc(
				{
					"doctype": "POS Print Template",
					"title": title,
					"title_ar": f"{title_ar} {paper_width}",
					"template_type": template_type,
					"paper_width": paper_width,
					"is_default": 1,
					"template_html": body,
				}
			).insert(ignore_permissions=True)


def _was_edited(row) -> bool:
	"""Has a person changed this since it was installed?

	A second of tolerance because `creation` and `modified` are stamped by
	separate calls on insert and can land microseconds apart — a difference that
	would otherwise read as an edit and freeze every shipped template for ever.
	"""
	if not row.modified or not row.creation:
		return False

	return abs(time_diff_in_seconds(row.modified, row.creation)) > 1

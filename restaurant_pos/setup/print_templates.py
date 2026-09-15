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

#: Root font size per paper width, so `rem` means the same physical size on
#: every roll. 80mm prints 576 dots, 58mm prints 384 — two thirds of it.
#:
#: **The unit here is a printer dot, 1/203 inch — not a screen pixel**, and
#: reading it as one cost this receipt its legibility. 16 looked like an
#: ordinary 16px body and is nothing of the kind: it is a 5.7pt font, and it
#: fitted seventy characters to an 80mm line where a receipt holds forty-odd. A
#: working ERPNext receipt from another site sets 10pt, which at 203 dpi is 28
#: dots, and that difference is what "the text is small" meant.
#:
#: Sized for about 44 characters to a line on 80mm, 32 on 58mm.
ROOT_PX = {
	"58mm": 22,
	"76mm": 24,
	"80mm": 26,
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
/* `min-width: 0` on every cell, for the reason spelled out at `.row` below: a
 * flex item refuses to shrink under its own content by default, so a long
 * Arabic label does not wrap — it overruns the figure beside it. The tax
 * description printed straight through the amount. */
.tri > * { min-width: 0; }
/* **Keep the Arabic labels short enough to fit on one line — about twelve
 * characters.** This renderer will not break an Arabic run inside a narrow flex
 * cell. It does not clip it or wrap it: it prints it straight over whatever is
 * beside it, and "الإجمالي قبل الضريبة" came out superimposed on the amount on
 * 76mm paper while "VAT 15%" in the cell alongside wrapped correctly.
 *
 * Dropping `unicode-bidi: isolate` from these cells was the obvious suspect and
 * changed nothing, so it is gone on its own merits — a flex item is a block box
 * and starts its own bidi context anyway. Not needing the break is the only
 * thing that works. `.amt` keeps its isolate: an amount is short, must not
 * wrap, and must not be reordered into the label beside it. */
.tri > .en { flex: 0 0 28%; text-align: left; }
.tri > .val { flex: 1 1 auto; text-align: center; }
.tri > .ar { flex: 0 0 30%; text-align: right; direction: rtl; }
/* Dates and document numbers are reference, not headline: set smaller so they
 * fit one line instead of wrapping mid-number. */
.meta { font-size: 0.88rem; }
.rule { border-top: 1px solid #000; margin: 0.35rem 0; }
/* The one line a customer checks before walking away, so it is the one thing on
 * the receipt that is unmistakable at arm's length. */
.pay { border-top: 2px solid #000; border-bottom: 2px solid #000;
	margin: 0.4rem 0; padding: 0.25rem 0; font-size: 1.45rem; font-weight: bold; }
.logo { max-width: 50%; }
.stars { letter-spacing: 0.08em; }
/* An item is two lines, not four columns.
 *
 * Taken from a working ERPNext receipt, which puts the name on a row of its
 * own. Four columns leave the name about a third of the roll, and the font has
 * to shrink until it fits — the columns were being paid for in legibility, on
 * the one thing a customer actually reads. */
.item { padding: 0.2rem 0; }
.item .nm { font-weight: bold; }
.item .fig { padding-left: 1rem; font-size: 0.92rem; }
/* Saudi practice, and the reference receipt says it in a box: a customer
 * looking at a price needs to know the tax is already in it. */
.notice { border: 1px dashed #000; padding: 0.25rem; margin: 0.35rem 0;
	text-align: center; font-size: 0.9rem; font-weight: bold; }
/* A kitchen ticket's modifiers and notes are not annotations — "بدون ملح" is
 * the whole instruction, and one a cook scanning a rail must not miss. Set
 * below the item name, but not so far below that it reads as small print. */
.mod { font-size: 1.15rem; padding-right: 1.2rem; }
.note { font-size: 1.25rem; font-weight: bold; padding-right: 1.2rem; }
/* Quantity first, and placed by the layout rather than by the bidi algorithm.
 *
 * Written as one line — an isolated "2&times;" then the name — it printed with
 * the quantity on the *left*, at the end of an RTL line, though the source has
 * it first. A cook scans the right edge of an Arabic ticket for numbers, and
 * would be reading them off the wrong side of every line. A flex row puts the
 * first child at the start edge and the renderer has no say in it. */
.kitem { padding: 0.3rem 0; }
.kline { display: flex; align-items: baseline; }
/* A physical margin, and not the row's `gap`. **This renderer supports
 * neither flex `gap` nor CSS logical properties** — it drops both without
 * complaint, and "2&times;برغر كلاسيك" printed with the quantity welded to
 * the name while every modifier sat flush against the edge. Logical
 * properties are the rule everywhere else in this project; a print template
 * is always RTL and always drawn by this one engine, so here they are
 * physical on purpose. */
.kline > .q { flex: 0 0 auto; font-size: 1.6rem; font-weight: bold;
	direction: ltr; unicode-bidi: isolate; margin-left: 0.6rem; }
.kline > .n { flex: 1 1 auto; min-width: 0; font-size: 1.5rem; font-weight: bold; }
/* Not a heading — a warning. A cook who reads an addition ticket as a new order
 * cooks the whole order twice, and one who misses a void ticket cooks something
 * nobody is paying for. Reversed out so it cannot be skimmed past. */
.banner { background: #000; color: #fff; text-align: center; font-weight: bold;
	font-size: 1.5rem; padding: 0.25rem; margin: 0.4rem 0; }
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
	{{% if tax_inclusive %}}
	<div class="notice">الأسعار شاملة ضريبة القيمة المضافة</div>
	{{% endif %}}
	<hr>
	{{# A centred line each, not one row holding both. Side by side they came out
	    printed over each other on 76mm paper: two long headings in one flex row
	    is exactly the case this renderer lays out wrong, and a heading is the
	    last thing on a receipt worth risking for one saved line.

	    A return is a credit note, and ZATCA treats it as a different document
	    type. Printing one headed "invoice" with negative amounts is wrong on
	    the paper the customer keeps. #}}
	<div class="c b">{{% if doc.is_return %}}إشعار دائن{{% else %}}فاتورة ضريبية مبسطة{{% endif %}}</div>
	<div class="c b">{{% if doc.is_return %}}Credit Note{{% else %}}Simplified Tax Invoice{{% endif %}}</div>
	{{% if order.daily_number %}}
	<div class="tri">
		<span class="en huge">{{{{ order.daily_number }}}}</span>
		<span class="val"></span>
		<span class="ar big">{{{{ order.order_type_title | rtl }}}}</span>
	</div>
	{{% endif %}}
	<hr>
	<div class="tri meta">
		<span class="en">Date</span>
		<span class="val">{{{{ frappe.utils.formatdate(doc.posting_date) }}}} {{{{ frappe.utils.format_time(doc.posting_time) }}}}</span>
		<span class="ar">التاريخ</span>
	</div>
	<div class="tri meta">
		<span class="en">Cashier</span>
		<span class="val">{{{{ (order.cashier_name or doc.owner) | rtl }}}}</span>
		<span class="ar">الكاشير</span>
	</div>
	<div class="tri meta">
		<span class="en">Invoice</span>
		<span class="val">{{{{ doc.name }}}}</span>
		<span class="ar">رقم الفاتورة</span>
	</div>
	{{% if order.table_number %}}
	<div class="tri meta">
		<span class="en">Table</span>
		<span class="val">{{{{ order.table_number }}}}</span>
		<span class="ar">الطاولة</span>
	</div>
	{{% endif %}}
	<div class="rule"></div>
	{{% for item in doc.items %}}
	<div class="item">
		<div class="nm">{{{{ item.item_name | rtl }}}}</div>
		<div class="row fig">
			<span class="amt">{{{{ item.qty | int }}}} &times; {{{{ "%.2f" | format(item.rate) }}}}</span>
			<span class="amt">{{{{ "%.2f" | format(item.amount) }}}}</span>
		</div>
	</div>
	{{% endfor %}}
	<div class="rule"></div>
	<div class="tri">
		<span class="en">Subtotal</span>
		<span class="val amt">{{{{ "%.2f" | format(doc.net_total) }}}}</span>
		<span class="ar">قبل الضريبة</span>
	</div>
	{{# The points are part of the invoice's discount — ZATCA treats them as one
	    (`D-189`) — but the guest spent their own balance, so they print as a
	    line of their own and the discount line carries only the rest. The two
	    still add up to the document's figure. #}}
	{{% set points_off = loyalty.amount if loyalty else 0 %}}
	{{% if doc.discount_amount - points_off > 0.005 %}}
	<div class="tri">
		<span class="en">Discount</span>
		<span class="val amt">{{{{ "%.2f" | format(doc.discount_amount - points_off) }}}}</span>
		<span class="ar">الخصم</span>
	</div>
	{{% endif %}}
	{{% if points_off %}}
	<div class="tri">
		<span class="en">Points {{{{ loyalty.spent }}}}</span>
		<span class="val amt">{{{{ "%.2f" | format(points_off) }}}}</span>
		<span class="ar">نقاط الولاء</span>
	</div>
	{{% endif %}}
	{{% for tax in doc.taxes %}}
	<div class="tri">
		<span class="en">VAT {{{{ "%g" | format(tax.rate) }}}}%</span>
		<span class="val amt">{{{{ "%.2f" | format(tax.tax_amount) }}}}</span>
		{{# The description carries the rate ("ضريبة القيمة المضافة 15%"), and a
		    digit in an Arabic label is the one thing this renderer cannot lay
		    out. The rate is already in the English cell. #}}
		<span class="ar">الضريبة</span>
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
	{{% if loyalty %}}
	{{# What the bill earned and what the guest now holds — the receipt is the
	    one thing they take home, and a scheme nobody sees is a scheme nobody
	    uses (`D-189`). No digit sits in an Arabic cell (`D-090`). #}}
	<hr>
	<div class="tri">
		<span class="en">Points earned</span>
		<span class="val amt">{{{{ loyalty.earned }}}}</span>
		<span class="ar">نقاط مكتسبة</span>
	</div>
	<div class="tri">
		<span class="en">Points balance</span>
		<span class="val amt">{{{{ loyalty.balance }}}}</span>
		<span class="ar">رصيد النقاط</span>
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
	{{# Before the food, not after it: by the time a cook reaches the items they
	    have already decided what kind of ticket this is. #}}
	{{% if doc.kot_type != "initial" %}}
	<div class="banner">
		{{% if doc.kot_type == "addition" %}}إضافة على الطلب
		{{% elif doc.kot_type == "void" %}}إلغاء أصناف
		{{% else %}}إعادة طباعة{{% endif %}}
	</div>
	{{% endif %}}
	<hr>
	<div class="row"><span>{{{{ station | rtl }}}}</span>
		<span class="amt">{{{{ frappe.utils.format_datetime(doc.sent_at, "HH:mm") }}}}</span></div>
	{{% if table_number %}}
	<div class="row big"><span>الطاولة</span><span class="amt">{{{{ table_number }}}}</span></div>
	{{% endif %}}
	<hr>
	{{% for item in doc.items %}}
	<div class="kitem">
		{{# Quantity in its own cell, and placed by the flex row rather than by
		    the bidi algorithm — as one line it printed at the *left* end, the
		    wrong side of an Arabic ticket to scan for numbers. It stays an
		    isolated LTR box for the older reason: a quantity, a multiplication
		    sign and an Arabic name in one run get mixed, and the digits land
		    inside the name. A cook reading a smeared quantity makes the wrong
		    number of plates. #}}
		<div class="kline">
			<span class="q">{{% if item.action == "void" %}}&#10005;{{% endif %}}{{{{ item.qty | int }}}}&times;</span>
			<span class="n">{{{{ item.item_name | rtl }}}}</span>
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
	<div class="note">{{{{ doc.order_notes | rtl }}}}</div>
	{{% endif %}}
	{{# Last and smallest. A cook never needs it; the person working out why a
	    plate was wrong an hour later does. #}}
	<hr>
	<div class="row muted"><span>{{{{ doc.cashier_name }}}}</span><span class="amt">{{{{ doc.name }}}}</span></div>
</body></html>
"""

#: The financial report, X while open and Z once closed (`D-219`).
#:
#: Drawn from the report `utils/shift` computes for the screen — never from a
#: closing entry, which is what this template used to read and what nothing ever
#: printed. One set of figures for the screen and the paper, or the two disagree.
#:
#: Taken from the user's Vitec report and the professional tills: a table per
#: section rather than Vitec's block repeated for every cashier, the counted
#: figure and its difference (Vitec has neither), voids by amount as well as
#: count, and credit marked as never having been in the drawer.
SHIFT_REPORT = """
<html><head><meta charset="utf-8"><style>{css}</style></head>
<body class="rtl">
	{{% if logo %}}<div class="c"><img class="logo" src="{{{{ logo }}}}" alt=""></div>{{% endif %}}
	<div class="c big">{{{{ (company.company_name or company.name) | rtl }}}}</div>
	{{% if branch %}}<div class="c">{{{{ branch | rtl }}}}</div>{{% endif %}}
	{{% if company.tax_id %}}<div class="c muted">الرقم الضريبي <span class="amt">{{{{ company.tax_id }}}}</span></div>{{% endif %}}
	<div class="banner">{{{{ "تقرير مالي نهائي" if kind == "Z" else "تقرير مالي مؤقت" }}}} <span class="amt">{{{{ kind }}}}</span></div>
	<div class="row meta"><span>من</span><span class="amt">{{{{ opened }}}}</span></div>
	<div class="row meta"><span>إلى</span><span class="amt">{{{{ closed }}}}</span></div>
	{{% if who %}}<div class="row meta"><span>الموظف</span><span>{{{{ who | rtl }}}}</span></div>{{% endif %}}

	<hr>
	<div class="b">المبيعات</div>
	<div class="row"><span>قبل الخصم</span><span class="amt">{{{{ "%.2f" | format(report.gross_sales) }}}}</span></div>
	<div class="row"><span>الخصومات</span><span class="amt">{{{{ "%.2f" | format(report.discounts) }}}}</span></div>
	<div class="row total"><span>الصافي</span><span class="amt">{{{{ "%.2f" | format(report.sales) }}}}</span></div>
	<div class="row"><span>المرتجعات</span><span class="amt">{{{{ "%.2f" | format(report.returns) }}}}</span></div>

	{{% if report.taxes %}}
	<hr>
	<div class="line head"><span class="name">الضريبة</span><span class="col">الصافي</span><span class="col">الضريبة</span><span class="col">الإجمالي</span></div>
	{{% for row in report.taxes %}}
	<div class="line"><span class="name"><span class="amt">{{{{ "%g" | format(row.rate) }}}}%</span></span><span class="col">{{{{ "%.2f" | format(row.net) }}}}</span><span class="col">{{{{ "%.2f" | format(row.tax) }}}}</span><span class="col">{{{{ "%.2f" | format(row.gross) }}}}</span></div>
	{{% endfor %}}
	{{% endif %}}

	{{% if report.by_method %}}
	<hr>
	<div class="line head"><span class="name">طريقة الدفع</span><span class="col">مبيعات</span><span class="col">مرتجع</span><span class="col">صافي</span></div>
	{{% for row in report.by_method %}}
	<div class="line"><span class="name">{{{{ row.method | rtl }}}}{{% if row.kind == "credit" %}} *{{% endif %}}</span><span class="col">{{{{ "%.2f" | format(row.taken) }}}}</span><span class="col">{{{{ "%.2f" | format(row.refunded) }}}}</span><span class="col">{{{{ "%.2f" | format(row.sales) }}}}</span></div>
	{{% endfor %}}
	{{% if report.credit_total %}}<div class="muted">* على حساب طرف آخر، ليست في الدرج</div>{{% endif %}}
	{{% endif %}}

	{{% if drawers %}}
	<hr>
	<div class="line head"><span class="name">الدرج</span><span class="col">متوقّع</span><span class="col">معدود</span><span class="col">الفرق</span></div>
	{{% for drawer in drawers %}}
	<div class="line"><span class="name">{{{{ drawer.name | rtl }}}}</span><span class="col">{{{{ "%.2f" | format(drawer.expected) }}}}</span><span class="col">{{{{ "%.2f" | format(drawer.counted) if drawer.counted is not none else "-" }}}}</span><span class="col">{{{{ "%.2f" | format(drawer.difference) if drawer.difference is not none else "-" }}}}</span></div>
	{{% if drawer.opening %}}<div class="row muted"><span>منها افتتاحي</span><span class="amt">{{{{ "%.2f" | format(drawer.opening) }}}}</span></div>{{% endif %}}
	{{% endfor %}}
	{{% endif %}}

	{{% if report.by_cashier | length > 1 %}}
	<hr>
	<div class="line head"><span class="name">الموظف</span><span class="col">فواتير</span><span class="col">مبيعات</span><span class="col">مرتجع</span></div>
	{{% for person in report.by_cashier %}}
	<div class="line"><span class="name">{{{{ person.name | rtl }}}}</span><span class="col">{{{{ person.count }}}}</span><span class="col">{{{{ "%.2f" | format(person.sales) }}}}</span><span class="col">{{{{ "%.2f" | format(person.returns) }}}}</span></div>
	{{% endfor %}}
	{{% endif %}}

	<hr>
	<div class="b">الاستثناءات</div>
	<div class="row"><span>فواتير مدفوعة</span><span class="amt">{{{{ report.orders.closed }}}}</span></div>
	<div class="row"><span>إلغاء بعد المطبخ</span><span class="amt">{{{{ report.voids }}}} / {{{{ "%.2f" | format(report.void_amount) }}}}</span></div>
	<div class="row"><span>طلبات ملغاة</span><span class="amt">{{{{ report.orders.cancelled }}}}</span></div>
	{{% if report.orders.still_open %}}<div class="row"><span>فواتير مفتوحة</span><span class="amt">{{{{ report.orders.still_open }}}} / {{{{ "%.2f" | format(report.open_amount) }}}}</span></div>{{% endif %}}

	{{% if report.by_order_type %}}
	<hr>
	<div class="b">حسب نوع الطلب</div>
	{{% for row in report.by_order_type %}}
	<div class="row"><span>{{{{ (row.title_ar or row.order_type) | rtl }}}}</span><span class="amt">{{{{ row.count }}}} / {{{{ "%.2f" | format(row.sales) }}}}</span></div>
	{{% endfor %}}
	{{% endif %}}

	<hr>
	<div class="c muted">طُبع <span class="amt">{{{{ printed_at }}}}</span></div>
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

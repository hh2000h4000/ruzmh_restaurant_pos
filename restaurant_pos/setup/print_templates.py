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

#: Root font size in px per paper width, so `rem` means the same physical size
#: on every roll. 80mm prints 576 dots, 58mm prints 384 — two thirds of it.
ROOT_PX = {
	"58mm": 11,
	"76mm": 12,
	"80mm": 16,
}

#: Shared by every template. Arabic first in the stack, then whatever the server
#: has: if the box is missing an Arabic face the receipt still renders, it just
#: renders plainly — which is a better failure than a page of empty boxes.
BASE_CSS = """
@page { margin: 0; }
* { box-sizing: border-box; }
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
table { width: 100%; border-collapse: collapse; }
td, th { padding: 0.1rem 0; vertical-align: top; font-size: 0.95rem; }
th { border-bottom: 1px solid #000; text-align: start; font-weight: bold; }
.num { text-align: end; white-space: nowrap; }
.row { display: flex; justify-content: space-between; gap: 0.5rem; }
.total { font-size: 1.3rem; font-weight: bold; }
"""

CUSTOMER_RECEIPT = """
<html><head><meta charset="utf-8"><style>{css}</style></head>
<body class="rtl">
	<div class="c">
		<div class="big">{{{{ company.company_name or company.name }}}}</div>
		{{% if branch %}}<div>{{{{ branch.branch }}}}</div>{{% endif %}}
		{{% if company.tax_id %}}<div class="muted">الرقم الضريبي: {{{{ company.tax_id }}}}</div>{{% endif %}}
		<div class="muted">فاتورة ضريبية مبسطة</div>
	</div>
	<hr>
	<div class="row"><span>رقم الطلب</span><b>{{{{ order.daily_number or doc.name }}}}</b></div>
	<div class="row"><span>التاريخ</span><span>{{{{ frappe.utils.format_datetime(doc.posting_date) }}}}</span></div>
	<div class="row"><span>الكاشير</span><span>{{{{ order.cashier_name or doc.owner }}}}</span></div>
	{{% if order.order_type_title %}}
	<div class="row"><span>نوع الطلب</span><span>{{{{ order.order_type_title }}}}</span></div>
	{{% endif %}}
	{{% if order.table %}}<div class="row"><span>الطاولة</span><span>{{{{ order.table }}}}</span></div>{{% endif %}}
	<hr>
	<table>
		<tr><th>الصنف</th><th class="num">الكمية</th><th class="num">السعر</th><th class="num">الإجمالي</th></tr>
		{{% for item in doc.items %}}
		<tr>
			<td>{{{{ item.item_name }}}}</td>
			<td class="num">{{{{ item.qty | int }}}}</td>
			<td class="num">{{{{ "%.2f" | format(item.rate) }}}}</td>
			<td class="num">{{{{ "%.2f" | format(item.amount) }}}}</td>
		</tr>
		{{% endfor %}}
	</table>
	<hr>
	<div class="row"><span>الإجمالي قبل الضريبة</span><span>{{{{ "%.2f" | format(doc.net_total) }}}}</span></div>
	{{% if doc.discount_amount %}}
	<div class="row"><span>الخصم</span><span>{{{{ "%.2f" | format(doc.discount_amount) }}}}</span></div>
	{{% endif %}}
	{{% for tax in doc.taxes %}}
	<div class="row"><span>{{{{ tax.description }}}}</span><span>{{{{ "%.2f" | format(tax.tax_amount) }}}}</span></div>
	{{% endfor %}}
	<div class="row total"><span>الإجمالي</span><span>{{{{ "%.2f" | format(doc.rounded_total or doc.grand_total) }}}} ر.س</span></div>
	<hr>
	{{% for payment in doc.payments %}}
	<div class="row"><span>{{{{ payment.mode_of_payment }}}}</span><span>{{{{ "%.2f" | format(payment.amount) }}}}</span></div>
	{{% endfor %}}
	{{% if doc.change_amount %}}
	<div class="row"><span>الباقي</span><span>{{{{ "%.2f" | format(doc.change_amount) }}}}</span></div>
	{{% endif %}}
	<hr>
	<div class="c muted">شكراً لزيارتكم</div>
</body></html>
"""

BILL_PREVIEW = """
<html><head><meta charset="utf-8"><style>{css}</style></head>
<body class="rtl">
	<div class="c">
		<div class="big">{{{{ company.company_name or company.name }}}}</div>
		<div class="big">— غير ضريبية —</div>
		<div class="muted">للمراجعة فقط، ليست فاتورة</div>
	</div>
	<hr>
	<div class="row"><span>رقم الطلب</span><b>{{{{ doc.daily_number or doc.name }}}}</b></div>
	{{% if doc.table %}}<div class="row"><span>الطاولة</span><span>{{{{ doc.table }}}}</span></div>{{% endif %}}
	<div class="row"><span>الكاشير</span><span>{{{{ doc.cashier_name }}}}</span></div>
	<hr>
	<table>
		<tr><th>الصنف</th><th class="num">الكمية</th><th class="num">الإجمالي</th></tr>
		{{% for item in doc.items %}}
		{{% if not item.is_void %}}
		<tr>
			<td>{{{{ item.item_name }}}}</td>
			<td class="num">{{{{ item.qty | int }}}}</td>
			<td class="num">{{{{ "%.2f" | format(item.amount) }}}}</td>
		</tr>
		{{% endif %}}
		{{% endfor %}}
	</table>
	<hr>
	<div class="row total"><span>الإجمالي</span><span>{{{{ "%.2f" | format(totals.grand_total) }}}} ر.س</span></div>
	<div class="c muted">شامل ضريبة القيمة المضافة</div>
</body></html>
"""

KOT = """
<html><head><meta charset="utf-8"><style>{css}</style></head>
<body class="rtl">
	<div class="c huge">{{{{ doc.order_type_title or "" }}}}</div>
	<div class="c huge">#{{{{ doc.daily_number }}}}</div>
	{{% if doc.call_name %}}<div class="c big">{{{{ doc.call_name }}}}</div>{{% endif %}}
	<hr>
	<div class="row"><span>{{{{ doc.production_center }}}}</span>
		<span>{{{{ frappe.utils.format_datetime(doc.sent_at, "HH:mm") }}}}</span></div>
	{{% if doc.table %}}<div class="row"><span>الطاولة</span><b>{{{{ doc.table }}}}</b></div>{{% endif %}}
	<div class="row muted"><span>{{{{ doc.cashier_name }}}}</span><span>{{{{ doc.name }}}}</span></div>
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
		<div class="big">
			{{% if item.action == "void" %}}&#10005; {{% endif %}}{{{{ item.qty | int }}}} &times; {{{{ item.item_name }}}}
		</div>
		{{% if item.modifiers %}}
		{{% for modifier in frappe.parse_json(item.modifiers) %}}
		<div style="padding-inline-start: 1rem;">+ {{{{ modifier.get("title") or modifier.get("item_name") or modifier }}}}</div>
		{{% endfor %}}
		{{% endif %}}
		{{% if item.notes %}}<div style="padding-inline-start: 1rem;"><b>{{{{ item.notes }}}}</b></div>{{% endif %}}
	</div>
	{{% endfor %}}
	{{% if doc.order_notes %}}
	<hr>
	<div class="big">{{{{ doc.order_notes }}}}</div>
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
	<table>
		<tr><th>طريقة الدفع</th><th class="num">متوقّع</th><th class="num">معدود</th><th class="num">الفرق</th></tr>
		{{% for row in doc.payment_reconciliation %}}
		<tr>
			<td>{{{{ row.mode_of_payment }}}}</td>
			<td class="num">{{{{ "%.2f" | format(row.expected_amount) }}}}</td>
			<td class="num">{{{{ "%.2f" | format(row.closing_amount) }}}}</td>
			<td class="num">{{{{ "%.2f" | format(row.difference) }}}}</td>
		</tr>
		{{% endfor %}}
	</table>
	<hr>
	<div class="row total"><span>صافي المبيعات</span><span>{{{{ "%.2f" | format(doc.grand_total) }}}}</span></div>
	<div class="row"><span>عدد الفواتير</span><span>{{{{ doc.pos_transactions | length }}}}</span></div>
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

	An existing document is left completely alone. A restaurant that edited its
	receipt must not find the edit gone after a migrate — that is a change
	nobody made, arriving without warning, in the thing the customer is handed.
	"""
	for template_type, (title_ar, title_en, html) in SOURCES.items():
		for paper_width, root_px in ROOT_PX.items():
			title = f"{title_en} {paper_width}"
			if frappe.db.exists("POS Print Template", title):
				continue

			css = f"html {{ font-size: {root_px}px; }}" + BASE_CSS
			frappe.get_doc(
				{
					"doctype": "POS Print Template",
					"title": title,
					"title_ar": f"{title_ar} {paper_width}",
					"template_type": template_type,
					"paper_width": paper_width,
					"is_default": 1,
					"template_html": html.format(css=css).strip(),
				}
			).insert(ignore_permissions=True)

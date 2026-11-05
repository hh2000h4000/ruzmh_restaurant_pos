# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Whitelisted printing endpoints.

Two audiences, and they authorise differently. The **agent** endpoints are
called by a program inside the restaurant signed in as its own user, and are
scoped by `pos_print_agent.for_session()` — the agent may only ever see work
addressed to it. The **till** endpoints are called by a person at the till, and
go through `validate_branch_access` like everything else. The **desk** endpoints
— the test page and the template preview — serve a form, and are guarded by that
form's own permission (`D-208`), so a System Manager with no till role can still
test a printer they are configuring.

Refs: 07_API_Design.md, FR-6.4, FR-7.3, BR-072, D-084
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime

from restaurant_pos.restaurant_pos.doctype.pos_print_agent import pos_print_agent
from restaurant_pos.utils import idempotency
from restaurant_pos.utils import printing as service
from restaurant_pos.utils.audit import log_audit
from restaurant_pos.utils.deadlock import retried
from restaurant_pos.utils.permissions import assert_permission, validate_branch_access
from restaurant_pos.utils.sale_doc import SALE

#: Enough that a busy till does not need several round trips, few enough that a
#: crashed agent strands a small number of tickets.
CLAIM_BATCH = 5


# --------------------------------------------------------------------------- #
# The agent
# --------------------------------------------------------------------------- #


@frappe.whitelist()
def claim(
	version: str | None = None, host: str | None = None, settings: bool | int | str | None = None
) -> dict:
	"""Hand the calling agent its next jobs, and mark them as taken.

	With ``settings``, its settings come in the same answer (`_settings_for`):
	the minute's safety ask and the minute's settings are one request, not two
	(`D-418`). There is no other way to ask for them (`D-423`).

	The agent asks; the server never calls out. That is what lets a restaurant
	run behind an ordinary router with no fixed address, no forwarded port and
	no firewall exception — which is the difference between an install a
	technician can do in ten minutes and one that needs the ISP.

	**A job is handed out once, ever** (`D-405`). Nothing here takes back a job
	an agent never reported on: that is `utils.printing.sweep_jobs`'s to call
	unconfirmed, and the cashier's to reprint.
	"""
	agent_name = pos_print_agent.for_session()
	agent = frappe.get_doc("POS Print Agent", agent_name)
	agent.seen(version=version, host=host)

	service.expire_old(agent_name)

	queued = frappe.get_all(
		"POS Print Job",
		# A till's paper went to its agent from the till itself (`D-415`).
		filters={"agent": agent_name, "status": "queued", "is_direct": 0},
		fields=["name", "printer", "job_type", "copies", "payload"],
		order_by="creation asc",
		limit=CLAIM_BATCH,
	)

	jobs = []
	for row in queued:
		# Read under a row lock before taking it. A plain re-read is two steps,
		# and two polls between them took the same ticket: measured, sixty jobs
		# were taken a hundred and fifty times (`docs/15` §7). The lock makes the
		# second wait for the first to commit and then read "claimed". Oldest
		# first, always, so two pollers lock in the same order and never wait on
		# each other in a circle.
		if frappe.db.get_value("POS Print Job", row.name, "status", for_update=True) != "queued":
			continue

		frappe.db.set_value(
			"POS Print Job",
			row.name,
			{"status": "claimed", "claimed_at": now_datetime()},
			update_modified=False,
		)
		jobs.append(row | {"printer": _connection(row.printer)})

	if frappe.parse_json(settings or 0):
		return {"jobs": jobs, "settings": _settings_for(agent_name)}
	return {"jobs": jobs}


@frappe.whitelist()
def report(
	job: str,
	printed: bool | int | str,
	error: str | None = None,
	reason: str | None = None,
	nothing_sent: bool | int | str | None = None,
) -> dict:
	"""The agent says what happened to one job.

	A failure re-queues the ticket on the fallback printer here rather than in
	the agent: the fallback may belong to a different agent, and an agent that
	could redirect work to another one would be an agent that could print
	anything anywhere. **Only a failure that sent nothing** goes there
	(`D-405`).

	**``nothing_sent`` is said by the agent** (`D-414`): it is the one that knows
	whether a byte left it. Not said is not known: unconfirmed.
	"""
	agent_name = pos_print_agent.for_session()
	if frappe.db.get_value("POS Print Job", job, "agent") != agent_name:
		frappe.throw(_("That job was not given to this agent."), frappe.PermissionError)

	service.settle(
		job,
		printed=bool(frappe.parse_json(printed)),
		error=error,
		reason=reason,
		nothing_sent=bool(frappe.parse_json(nothing_sent or 0)),
	)

	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def not_handed(job: str, error: str | None = None) -> dict:
	"""The till drew its paper but its agent did not answer (`D-415`, `docs/15` §5.3).

	A till endpoint: the cashier's own branch only. The paper becomes
	unconfirmed — the till cannot tell "never arrived" from "printed, answer
	lost" — and a kitchen ticket rings the bell. Nothing is printed again.
	"""
	branch = frappe.db.get_value("POS Print Job", job, "branch")
	if not branch:
		frappe.throw(_("Print job {0} does not exist.").format(job))
	validate_branch_access(branch)

	service.mark_not_handed(job, error or _("The print agent did not answer."))
	return {"ok": True}


def _settings_for(agent_name: str) -> dict:
	"""What an agent needs to take paper straight from a till (`D-414`, `docs/15` §5.9).

	- ``token`` — the key every till's request must carry.
	- ``origins`` — the only pages it takes paper from: this site, by the address
	  the agent itself reaches it at and by the site's own name. Another page in
	  the same browser is refused even if it knows the port.
	- ``listen_on_network`` — off unless set on the agent's form: it hears its
	  own computer only, and a phone or a tablet needs it on.
	- ``socket`` — where the server rings when it queues paper (`D-418`): the
	  site's namespace, and on a development bench the port, which is not the
	  site's. In production the site's own address passes it on.

	Sent with the claim when the agent starts and again every minute, so a change
	on the form, or a key issued again, reaches it without anyone at the computer.
	"""
	return {
		"token": pos_print_agent.direct_token(agent_name),
		"origins": _site_origins(),
		"listen_on_network": bool(frappe.db.get_value("POS Print Agent", agent_name, "listen_on_network")),
		"socket": {
			"site": frappe.local.site,
			"port": frappe.conf.socketio_port if getattr(frappe.local, "dev_server", False) else None,
		},
	}


def _site_origins() -> list[str]:
	from urllib.parse import urlsplit

	from frappe.utils import get_url

	origins = []
	for url in (frappe.request.host_url if frappe.request else None, get_url()):
		if not url:
			continue
		parts = urlsplit(url)
		origin = f"{parts.scheme}://{parts.netloc}"
		if origin not in origins:
			origins.append(origin)
	return origins


def _connection(printer: str) -> dict:
	"""Everything the agent needs to reach one printer, and nothing else."""
	doc = frappe.get_cached_doc("POS Printer", printer)
	return {
		"name": doc.name,
		"title": doc.title,
		"connection_type": doc.connection_type,
		"ip_address": doc.ip_address,
		"port": doc.port,
		"usb_vendor_id": doc.usb_vendor_id,
		"usb_product_id": doc.usb_product_id,
		# D-212 — a printer installed in Windows, reached through its spooler.
		"windows_printer_name": doc.get("windows_printer_name"),
	}


# --------------------------------------------------------------------------- #
# The till and the desk
# --------------------------------------------------------------------------- #


@frappe.whitelist()
@retried
def reprint_receipt(invoice_name: str, queue_id: str | None = None) -> dict:
	"""Print a receipt the customer has already been given (`FR-7.5`, `D-143`).

	**One endpoint for a sale and for a refund**, because it is one question: put
	this invoice on the cashier's printer again. A credit note is an invoice in
	reverse — it is asked for by the same cashier, at the same counter, for the
	same reason (the paper tore, the customer wants it for their employer), and a
	second endpoint would be a second thing to keep working (`CLAUDE.md` §5.5).

	Nothing is created. The reprint renders the document that exists, so the
	receipt that comes out is the receipt that was issued, and the trail lives in
	the audit log — which is exactly how a kitchen ticket reprints (`FR-6.4`).
	"""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	invoice = frappe.db.get_value(
		SALE, invoice_name, ["name", "docstatus", "is_return", "return_against"], as_dict=True
	)
	if not invoice:
		frappe.throw(_("Invoice {0} does not exist.").format(invoice_name))

	if invoice.docstatus != 1:
		frappe.throw(_("Invoice {0} is not submitted.").format(invoice_name))

	# The bill behind the paper. A credit note's own `sales_invoice` link is on
	# no order — it reverses one — so a refund is traced through the sale it was
	# taken against. Both branches end at the same order, which is what carries
	# the branch, the terminal and the printer this is going to.
	order = frappe.db.get_value(
		"Restaurant Order",
		{"sales_invoice": invoice.return_against or invoice.name},
		["name", "branch", "pos_profile"],
		as_dict=True,
	)
	if not order:
		frappe.throw(_("Invoice {0} did not come from this till.").format(invoice_name))

	validate_branch_access(order.branch)
	assert_permission("can_reprint_receipt")

	# **Refuse before promising** (`D-148`). The render happens off the request,
	# so nothing downstream can tell the cashier that this terminal has no
	# printer: `print_receipt` gives up quietly by design — the money has already
	# moved and a printer must never undo that — and the screen would have said
	# "sent to the printer" over a queue that produced nothing. Found by pressing
	# the button on a live till and watching no job appear.
	profile = frappe.db.get_value(SALE, invoice.name, "pos_profile")
	if not service.receipt_printer(profile, order.name):
		frappe.throw(_("No printer is linked to this terminal, so nothing can be printed."))

	service.enqueue_print("print_receipt", invoice_name=invoice.name, order_name=order.name)

	log_audit(
		"reprint_receipt",
		branch=order.branch,
		pos_profile=order.pos_profile,
		restaurant_order=order.name,
		details={"sales_invoice": invoice.name, "is_return": int(invoice.is_return or 0)},
	)

	result = {"invoice": invoice.name, "order_name": order.name, "queued": True}
	idempotency.remember(
		queue_id,
		"reprint_receipt",
		result,
		reference_doctype=SALE,
		reference_name=invoice.name,
	)
	return result


@frappe.whitelist()
def test_print(printer: str) -> dict:
	"""Put a known page through a printer (`D-085`).

	The first question anybody asks a printer setup screen is "is this thing
	plugged in?", and every professional POS answers it with a button. Without
	one the first real test is a customer's receipt during service.

	It also answers the second question, which is worse because it looks like a
	template bug: **is the paper the width we think it is?** (`D-111`)
	"""
	doc = frappe.get_doc("POS Printer", printer)
	frappe.has_permission("POS Printer", "write", doc=doc, throw=True)

	width = service.print_dots(doc)
	rendered = service.png_to_escpos(
		service.html_to_png(
			frappe.render_template(
				TEST_PAGE,
				{
					"printer": doc,
					"now": frappe.utils.format_datetime(now_datetime()),
					"agent": doc.print_agent,
					"width": width,
					# The paper widths, and 512 between 76mm and 80mm: a 180 dpi head
					# on 80mm paper, whose number goes in Print Width (`D-215`).
					"marks": sorted(
						(dots, name)
						for name, dots in (service.PAPER_DOTS | {"512": service.HEAD_DOTS_180_DPI}).items()
						if dots <= width
					),
				},
			),
			width_dots=width,
		),
		cut=bool(doc.cut_after_print),
	)

	# A test page is the printer's own: its branch is the printer's (`D-363`).
	job = service.queue(
		printer=printer,
		branch=frappe.db.get_value("POS Printer", printer, "branch"),
		job_type="test",
		rendered=rendered,
	)

	return {"job": job}


@frappe.whitelist()
def preview_template(template: str) -> dict:
	"""Render a template against a real document and hand back the bitmap.

	**Designing a receipt blind does not work**, and this project has the scars
	to prove it: a currency that ran into the total, item names sheared off the
	roll, a date reading 00:00:00, and a threshold that silently deleted every
	full stop — each one written in correct HTML, each one found by looking at
	the output rather than at the markup (`D-086`, `D-087`, `D-109`).

	So the preview is the **same pipeline the printer gets**, down to the
	one-bit conversion: rendered, thresholded, and shown at the paper's real dot
	width. A preview that skipped that would be a browser screenshot, which is
	exactly the thing that flattered every one of those defects.
	"""
	doc = frappe.get_doc("POS Print Template", template)
	frappe.has_permission("POS Print Template", "read", doc=doc, throw=True)

	context = _sample_context(doc.template_type)
	if not context:
		frappe.throw(_("Nothing to preview with: this site has no {0} yet.").format(_(doc.template_type)))

	html = frappe.render_template(doc.template_html, context)
	png = service.html_to_png(html, width_dots=service.PAPER_DOTS[doc.paper_width])

	# Through the one-bit conversion, then back to PNG: what the paper gets.
	import base64
	import io

	from PIL import Image

	image = Image.open(io.BytesIO(png)).convert("L")
	image = image.point(lambda value: 0 if value < service.INK_THRESHOLD else 255, mode="1")

	out = io.BytesIO()
	image.save(out, format="PNG")

	return {
		"image": f"data:image/png;base64,{base64.b64encode(out.getvalue()).decode('ascii')}",
		"width_dots": image.size[0],
		"height_dots": image.size[1],
		"sample": context.get("_sample"),
	}


def _sample_context(template_type: str) -> dict | None:
	"""A real document of the right kind, or nothing.

	Real rather than invented: a made-up order has tidy short names and round
	numbers, and every layout fault this project has had came from the awkward
	real ones — a long Arabic dish, a table id, a tax description with digits in
	it.
	"""
	if template_type == "kot":
		name = frappe.db.get_value("Kitchen Order Ticket", {}, "name", order_by="creation desc")
		if not name:
			return None
		kot = frappe.get_doc("Kitchen Order Ticket", name)
		center = frappe.get_doc("Production Center", kot.production_center) if kot.production_center else None
		return service.kot_context(kot, center) | {"_sample": name}

	if template_type in ("customer_receipt", "bill_preview"):
		name = frappe.db.get_value(SALE, {"docstatus": 1, "is_pos": 1}, "name", order_by="creation desc")
		if not name:
			return None
		invoice = frappe.get_doc(SALE, name)
		order = frappe.db.get_value("Restaurant Order", {"sales_invoice": name}, "name")
		return service.receipt_context(invoice, service._receipt_order(order)) | {"_sample": name}

	# The financial report reads what the till prints (`D-219`). This handed it a
	# bare POS Closing Entry, the context of the report before D-219, and every
	# shift report template failed its preview on the first field it looked for.
	entry = frappe.db.get_value(
		"POS Opening Entry", {"docstatus": 1}, ["name", "pos_profile"], as_dict=True, order_by="creation desc"
	)
	if not entry:
		return None

	return service.shift_report_context(pos_profile=entry.pos_profile, opening_entry=entry.name) | {
		"_sample": entry.name
	}


# `D-209` — `jobs_for` and `retry` stood here for a print-status screen that was
# never built: no caller and no test, each whitelisted. The code is in the
# history if that screen is ever made.


#: Deliberately not a POS Print Template.
#:
#: A test page's whole job is to be independent of the templates — when a
#: receipt comes out wrong, this is what says whether the printer or the
#: template is at fault. A test page an administrator can edit cannot answer
#: that question.
TEST_PAGE = """
<html><head><meta charset="utf-8"></head>
<body style="font-family: 'Noto Naskh Arabic', 'Amiri', 'DejaVu Sans', sans-serif;
	margin: 0; padding: 8px; text-align: center;">
	<div style="font-size: 22px; font-weight: bold;">RPOS</div>
	<div style="font-size: 18px; direction: rtl;">صفحة تجريبية</div>
	<hr>
	<div style="font-size: 14px; text-align: left;">
		<div>{{ printer.title }}</div>
		<div>{{ printer.name }} &middot; {{ printer.paper_width }}{% if printer.print_width_dots %} &middot; {{ printer.print_width_dots }} dots{% endif %}</div>
		<div>{{ printer.connection_type }}
			{% if printer.ip_address %}{{ printer.ip_address }}:{{ printer.port }}{% endif %}</div>
		<div>{{ agent or "-" }}</div>
		<div>{{ now }}</div>
	</div>
	<hr>
	<div style="font-size: 13px; direction: rtl;">
		إذا قرأت هذا السطر كاملاً فالطابعة والاتصال سليمان.
	</div>

	<!-- The width ruler. Each label is drawn to the *left* of its mark, so the
	     label for the width that actually fits stays on the roll and the wider
	     ones fall off with the paper. A plain bar cannot say this: sent 576
	     dots wide to a printer that reaches 384, it runs to the edge of 58mm
	     paper and looks perfectly complete.

	     Anything meant to be read on a too-narrow printer has to live in the
	     left of the page, because the right is the part that goes missing. An
	     RTL line aligned right — the natural way to set it — is the first
	     thing to fall off. -->
	<div style="font-size: 12px; direction: rtl; text-align: left; margin-top: 12px;">
		آخر مقاس يظهر أسفله هو عرض الطابعة الحقيقي.
		وإن كان 512 فاكتبه في Print Width.
	</div>
	<div style="position: relative; width: {{ width }}px; height: 58px; margin: 6px -8px 0;">
		<div style="position: absolute; left: 0; top: 0; width: {{ width }}px;
			height: 8px; background: #000;"></div>
		{% for at, name in marks %}
		<div style="position: absolute; left: {{ at - 3 }}px; top: 0;
			width: 3px; height: 24px; background: #000;"></div>
		<div style="position: absolute; left: {{ at - 63 }}px; top: {{ 26 if loop.index0 % 2 == 0 else 40 }}px;
			width: 60px; direction: ltr; text-align: right; font-size: 12px;">{{ name }}</div>
		{% endfor %}
	</div>
</body></html>
"""


@frappe.whitelist(methods=["POST"])
def prepare_terminal_printing(pos_profile: str, windows_printer_name: str, paper_width: str = "80mm") -> dict:
	"""«Set up printing for this device»: its agent and receipt printer in one step (`D-402`).

	Makes an agent and a printer and changes the device, so the caller needs
	all three of those desk rights — the forms' own (`D-208`).
	"""
	from restaurant_pos.utils import terminal_printing

	frappe.has_permission("POS Profile", "write", pos_profile, throw=True)
	frappe.has_permission("POS Print Agent", "create", throw=True)
	frappe.has_permission("POS Printer", "create", throw=True)
	return terminal_printing.prepare(pos_profile, windows_printer_name, paper_width)

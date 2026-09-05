# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Whitelisted printing endpoints.

Two audiences, and they authorise differently. The **agent** endpoints are
called by a program inside the restaurant signed in as its own user, and are
scoped by `pos_print_agent.for_session()` — the agent may only ever see work
addressed to it. The **till and desk** endpoints are called by a person, and go
through `validate_branch_access` like everything else.

Refs: 07_API_Design.md, FR-6.4, FR-7.3, BR-072, D-084
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime

from restaurant_pos.restaurant_pos.doctype.pos_print_agent import pos_print_agent
from restaurant_pos.utils import idempotency
from restaurant_pos.utils import printing as service
from restaurant_pos.utils.audit import log_audit
from restaurant_pos.utils.permissions import assert_permission, validate_branch_access

#: How long a job may sit with an agent before another claim may take it back.
#:
#: An agent that is killed between claiming and printing leaves the ticket in
#: `claimed` forever, and a kitchen ticket that exists but never prints is the
#: worst state in this whole module: the order looks sent and no food is made.
STALE_CLAIM_SECONDS = 120

#: Enough that a busy till does not need several round trips, few enough that a
#: crashed agent strands a small number of tickets.
CLAIM_BATCH = 5

#: How long a queued job is still worth printing (`D-108`).
#:
#: **A kitchen ticket has a shelf life.** An agent that has been off all day and
#: connects at closing time would otherwise print every ticket the day queued —
#: sending a cook a rush of orders that were served hours ago, or cancelled.
#: Twenty minutes is longer than any outage a cook could work through and far
#: shorter than a service.
#:
#: A receipt is the same argument from the other side: a customer who left
#: without one an hour ago is not helped by it appearing now.
STALE_AFTER_MINUTES = 20


# --------------------------------------------------------------------------- #
# The agent
# --------------------------------------------------------------------------- #


@frappe.whitelist()
def claim(version: str | None = None, host: str | None = None) -> list[dict]:
	"""Hand the calling agent its next jobs, and mark them as taken.

	The agent asks; the server never calls out. That is what lets a restaurant
	run behind an ordinary router with no fixed address, no forwarded port and
	no firewall exception — which is the difference between an install a
	technician can do in ten minutes and one that needs the ISP.
	"""
	agent_name = pos_print_agent.for_session()
	agent = frappe.get_doc("POS Print Agent", agent_name)
	agent.seen(version=version, host=host)

	_reclaim_stale(agent_name)
	_expire_old(agent_name)

	queued = frappe.get_all(
		"POS Print Job",
		filters={"agent": agent_name, "status": "queued"},
		fields=["name", "printer", "job_type", "copies", "payload"],
		order_by="creation asc",
		limit=CLAIM_BATCH,
	)

	jobs = []
	for row in queued:
		# Re-read before taking it: a second poll overlapping the first would
		# otherwise hand the same ticket out twice, and two identical tickets in
		# the kitchen become two plates of food.
		if frappe.db.get_value("POS Print Job", row.name, "status") != "queued":
			continue

		frappe.db.set_value(
			"POS Print Job",
			row.name,
			{"status": "claimed", "claimed_at": now_datetime()},
			update_modified=False,
		)
		jobs.append(row | {"printer": _connection(row.printer)})

	return jobs


@frappe.whitelist()
def report(job: str, printed: bool | int | str, error: str | None = None) -> dict:
	"""The agent says what happened to one job.

	A failure re-queues the ticket on the fallback printer here rather than in
	the agent: the fallback may belong to a different agent, and an agent that
	could redirect work to another one would be an agent that could print
	anything anywhere.
	"""
	agent_name = pos_print_agent.for_session()
	if frappe.db.get_value("POS Print Job", job, "agent") != agent_name:
		frappe.throw(_("That job was not given to this agent."), frappe.PermissionError)

	service.settle(job, printed=bool(frappe.parse_json(printed)), error=error)

	return {"ok": True}


def _reclaim_stale(agent_name: str) -> None:
	"""Put back anything the agent took and never reported on."""
	cutoff = add_to_date(now_datetime(), seconds=-STALE_CLAIM_SECONDS)
	stale = frappe.get_all(
		"POS Print Job",
		filters={"agent": agent_name, "status": "claimed", "claimed_at": ("<", cutoff)},
		fields=["name", "attempts"],
	)
	for row in stale:
		frappe.db.set_value(
			"POS Print Job",
			row.name,
			{"status": "queued", "attempts": (row.attempts or 0) + 1},
			update_modified=False,
		)


def _expire_old(agent_name: str) -> None:
	"""Drop the backlog rather than print it (`D-108`).

	An agent that was switched off all day, or a printer nobody had plugged in
	yet, comes back to a queue full of tickets whose moment has passed. Printing
	them is not catching up — it is a cook receiving twenty orders that were
	served, cancelled or paid hours ago, with no way to tell which.

	Marked failed rather than deleted: "this was queued and never printed" is
	the answer to a question somebody will ask, and a row that vanished answers
	nothing. The fallback printer is not tried either — the same staleness
	applies there.
	"""
	cutoff = add_to_date(now_datetime(), minutes=-STALE_AFTER_MINUTES)
	stale = frappe.get_all(
		"POS Print Job",
		filters={"agent": agent_name, "status": "queued", "creation": ("<", cutoff)},
		pluck="name",
	)

	for name in stale:
		frappe.db.set_value(
			"POS Print Job",
			name,
			{
				"status": "failed",
				"error": f"Not printed within {STALE_AFTER_MINUTES} minutes; too late to be useful.",
			},
			update_modified=False,
		)

	if stale:
		frappe.log_error(f"{len(stale)} stale print jobs dropped for {agent_name}", "RPOS printing")


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
	}


# --------------------------------------------------------------------------- #
# The till and the desk
# --------------------------------------------------------------------------- #


@frappe.whitelist()
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
		"Sales Invoice", invoice_name, ["name", "docstatus", "is_return", "return_against"], as_dict=True
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
		reference_doctype="Sales Invoice",
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
	validate_branch_access(doc.branch)

	width = service.PAPER_DOTS[doc.paper_width]
	rendered = service.png_to_escpos(
		service.html_to_png(
			frappe.render_template(
				TEST_PAGE,
				{
					"printer": doc,
					"now": frappe.utils.format_datetime(now_datetime()),
					"agent": doc.print_agent,
					"width": width,
					"marks": sorted(
						(dots, name) for name, dots in service.PAPER_DOTS.items() if dots <= width
					),
				},
			),
			width_dots=width,
		),
		cut=bool(doc.cut_after_print),
	)

	job = service.queue(printer=printer, job_type="test", rendered=rendered)

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
	if doc.branch:
		validate_branch_access(doc.branch)

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
		center = frappe.get_doc("Production Center", kot.production_center)
		return service.kot_context(kot, center) | {"_sample": name}

	if template_type in ("customer_receipt", "bill_preview"):
		name = frappe.db.get_value(
			"Sales Invoice", {"docstatus": 1, "is_pos": 1}, "name", order_by="creation desc"
		)
		if not name:
			return None
		invoice = frappe.get_doc("Sales Invoice", name)
		order = frappe.db.get_value("Restaurant Order", {"sales_invoice": name}, "name")
		return service.receipt_context(invoice, service._receipt_order(order)) | {"_sample": name}

	name = frappe.db.get_value("POS Closing Entry", {}, "name", order_by="creation desc")
	if not name:
		return None

	return {"doc": frappe.get_doc("POS Closing Entry", name), "_sample": name}


@frappe.whitelist()
def jobs_for(reference_doctype: str, reference_name: str) -> list[dict]:
	"""Every print job raised for one document, newest first.

	Keyed by the document rather than by a job id because the job is created
	after the request that caused it returns — rendering happens off the request
	(`printing.enqueue_print`). The till knows the invoice it just settled; it
	cannot know a job that did not exist yet.

	An empty list is itself an answer, and the screen should say so: it means
	nothing was ever asked to print, which is a different problem from a printer
	that refused.
	"""
	jobs = frappe.get_all(
		"POS Print Job",
		filters={"reference_doctype": reference_doctype, "reference_name": reference_name},
		fields=["name", "status", "printer", "job_type", "error", "printed_at", "branch"],
		order_by="creation desc",
	)
	if jobs:
		validate_branch_access(jobs[0].branch)

	return jobs


@frappe.whitelist()
def retry(job: str) -> dict:
	"""Send a failed job again, to the same printer.

	The bytes are the ones already rendered, so what comes out is what should
	have come out the first time — the paper jam is fixed, not the receipt
	rewritten.
	"""
	doc = frappe.get_doc("POS Print Job", job)
	validate_branch_access(doc.branch)

	if doc.status not in ("failed", "printed"):
		frappe.throw(_("{0} has not finished yet.").format(job))

	doc.db_set(
		{"status": "queued", "error": None, "claimed_at": None, "printed_at": None},
		update_modified=False,
	)

	return {"job": doc.name, "status": "queued"}


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
		<div>{{ printer.name }} &middot; {{ printer.paper_width }}</div>
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

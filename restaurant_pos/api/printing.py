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
from restaurant_pos.utils import printing as service
from restaurant_pos.utils.permissions import validate_branch_access

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
def test_print(printer: str) -> dict:
	"""Put a known page through a printer (`D-085`).

	The first question anybody asks a printer setup screen is "is this thing
	plugged in?", and every professional POS answers it with a button. Without
	one the first real test is a customer's receipt during service.
	"""
	doc = frappe.get_doc("POS Printer", printer)
	validate_branch_access(doc.branch)

	rendered = service.png_to_escpos(
		service.html_to_png(
			frappe.render_template(
				TEST_PAGE,
				{
					"printer": doc,
					"now": frappe.utils.format_datetime(now_datetime()),
					"agent": doc.print_agent,
				},
			),
			width_dots=service.PAPER_DOTS[doc.paper_width],
		),
		cut=bool(doc.cut_after_print),
	)

	job = service.queue(printer=printer, job_type="test", rendered=rendered)

	return {"job": job}


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
</body></html>
"""

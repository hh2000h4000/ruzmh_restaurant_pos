# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Turning a document into bytes a thermal printer will accept.

`FR-7.3` had one function do all six steps, ending with a TCP socket to the
printer. It cannot: a cloud bench has no route into the restaurant's network,
and the browser that *is* on that network cannot open a socket at all. So the
steps split at the point where the bytes are ready (`D-084`) — this module does
one to three, an agent inside the restaurant does four to six:

    Jinja2 template  ->  HTML  ->  PNG  ->  ESC/POS  ->  [ POS Print Job ]
    ^------------------ here -----------------------^     ^-- the agent --^

**Everything prints as an image** (`FR-7.4`). Not a preference: thermal printers
carry their own Arabic code pages or none at all, they disagree about which, and
the ones that have it get the letter shapes wrong when words join. A bitmap has
no opinion about Arabic, so the same bytes come out right on every model.
"""

from __future__ import annotations

import base64
import io
import subprocess
from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import add_days, now_datetime, nowdate

#: Printable width in dots, by paper size, at the 203 dpi every one of these
#: printers uses. The paper is wider than the print head can reach — 80mm paper
#: prints 72mm — which is why these are not the millimetre figures times eight.
PAPER_DOTS = {
	"58mm": 384,
	"76mm": 420,
	"80mm": 576,
}

#: How many dot rows go in one raster command.
#:
#: `GS v 0` accepts far more, but a cheap printer's input buffer does not, and
#: the failure is a half-printed ticket rather than an error. Bands of 128 rows
#: are small enough for every model we list and cost nothing.
BAND_ROWS = 128

#: Long enough for a slow render, short enough that a wedged renderer does not
#: hold the request that queued the ticket.
RENDER_TIMEOUT = 20

#: Below this grey a dot fires. Measured on real paper, not chosen (`D-109`).
#:
#: The obvious midpoint, 128, keeps only the darkest core of each stroke and
#: throws the anti-aliased body away — and on a first real print that did not
#: read as "a bit light". Whole characters were **missing**: the colon in
#: `192.168.8.192:9100`, the full stop ending a sentence, the dots that tell
#: Arabic letters apart, and both horizontal rules, which vanished completely.
#:
#: 170 fires 60% more dots (1.79% of the page against 2.86%) and brings all of
#: them back. Higher gains almost nothing and starts filling the counters —
#: the holes inside letters — which on 203 dpi paper turns small Arabic into
#: a smudge.
INK_THRESHOLD = 170

ESC = b"\x1b"
GS = b"\x1d"

#: Initialise: clears any state the previous job left behind.
INIT = ESC + b"@"

#: Feed four lines, then a partial cut. The feed is what puts the tear line past
#: the print head instead of through the last line of the total.
FEED_AND_CUT = ESC + b"d" + bytes([4]) + GS + b"V" + bytes([66, 0])

#: Pulse timings for the cash drawer, in units of 2 ms: 50 ms on, 500 ms off.
#:
#: The solenoid needs a long enough pulse to throw the latch and a gap before it
#: could be pulsed again. Too short and a stiff drawer stays shut; far too long
#: and the coil cooks.
DRAWER_ON, DRAWER_OFF = 25, 250


@dataclass(frozen=True)
class Rendered:
	"""Bytes ready for a printer, and what they cost to make."""

	payload: bytes
	width_dots: int
	height_dots: int


# --------------------------------------------------------------------------- #
# 1. Which template
# --------------------------------------------------------------------------- #


def resolve_template(
	template_type: str,
	*,
	paper_width: str,
	branch: str | None = None,
	explicit: str | None = None,
) -> str:
	"""The template to render, most specific first.

	An explicit choice on the POS Profile or the Production Center wins; failing
	that a template for this branch; failing that the shipped default. The
	shipped default exists so that a restaurant prints correctly before anybody
	has opened this screen.
	"""
	if explicit:
		return explicit

	common = {"template_type": template_type, "paper_width": paper_width}

	if branch:
		for_branch = frappe.db.get_value("POS Print Template", common | {"branch": branch}, "name")
		if for_branch:
			return for_branch

	# `("in", ["", None])` looks like it says "either spelling of empty" and does
	# not: SQL never matches NULL inside IN, so a template saved with a NULL
	# branch is invisible and every print fails with "no template". Frappe's
	# "not set" compiles to an ifnull() and catches both.
	shipped = frappe.db.get_value(
		"POS Print Template",
		common | {"branch": ("is", "not set"), "is_default": 1},
		"name",
	)
	if not shipped:
		frappe.throw(
			_("No {0} template for {1} paper. Add one, or mark an existing one as default.").format(
				template_type, paper_width
			)
		)

	return shipped


# --------------------------------------------------------------------------- #
# 2. HTML
# --------------------------------------------------------------------------- #


#: RIGHT-TO-LEFT MARK.
RLM = "‏"


def rtl(text) -> str:
	"""Prefix an RLM to Arabic text that contains digits, and nothing else.

	A Jinja filter (`hooks.py`), written `{{ item.item_name | rtl }}` around
	every field that comes from the database.

	**Both halves of the condition were measured** (`D-090`). wkhtmltoimage's
	bidi is an old WebKit's, and it draws only the tail of an Arabic string that
	contains digits: "برغر لحم 200 جرام" — an ordinary menu item — came out as
	overlapping fragments, and "ضريبة القيمة المضافة 15%" as "ة 15%". An RLM
	fixes those. But the same RLM *breaks* plain Arabic: "شيش طاووق" became
	"ﺱ طاووق". `dir="rtl"`, `<bdi>`, `unicode-bidi` in three modes and a CSS
	`::before` were each tried and each failed on one side or the other.

	So the mark goes on exactly the strings that need it. A digit is the whole
	test, because a digit is what the renderer cannot lay out beside Arabic.
	"""
	text = "" if text is None else str(text)
	return RLM + text if any(character.isdigit() for character in text) else text


def render_html(template_name: str, context: dict) -> str:
	template = frappe.get_cached_doc("POS Print Template", template_name)
	return frappe.render_template(template.template_html, context)


# --------------------------------------------------------------------------- #
# 3. PNG
# --------------------------------------------------------------------------- #


def html_to_png(html: str, *, width_dots: int) -> bytes:
	"""Render HTML to a bitmap exactly `width_dots` wide.

	`--disable-smart-width` matters more than it looks: without it wkhtmltoimage
	widens the viewport to fit the content, and a receipt that is 700 dots wide
	prints with its right-hand column past the edge of the paper — on the paper
	it looks like the totals column was simply left off.
	"""
	command = [
		"wkhtmltoimage",
		"--format",
		"png",
		# Stated here rather than left to a `<meta charset>` in the template.
		# Reading from stdin, wkhtmltoimage assumes Latin-1 and every Arabic
		# letter comes out as two accented Latin ones — a receipt that is
		# unreadable but prints perfectly, so nothing reports it as an error.
		"--encoding",
		"utf-8",
		"--width",
		str(width_dots),
		"--disable-smart-width",
		"--quality",
		"100",
		"--enable-local-file-access",
		"--quiet",
		"-",  # read HTML from stdin
		"-",  # write PNG to stdout
	]

	try:
		result = subprocess.run(
			command,
			input=html.encode("utf-8"),
			capture_output=True,
			timeout=RENDER_TIMEOUT,
			check=False,
		)
	except FileNotFoundError:
		frappe.throw(_("wkhtmltoimage is not installed on the server, so nothing can be printed."))
	except subprocess.TimeoutExpired:
		frappe.throw(_("Rendering the document took too long."))

	if result.returncode != 0 or not result.stdout:
		# wkhtmltoimage writes its complaint to stderr and still exits 0 for
		# warnings, so the empty-output case has to be treated as failure too.
		detail = (result.stderr or b"").decode("utf-8", "replace").strip()
		frappe.log_error(f"wkhtmltoimage failed: {detail}", "RPOS printing")
		frappe.throw(_("The document could not be rendered for printing."))

	return result.stdout


# --------------------------------------------------------------------------- #
# 4. ESC/POS
# --------------------------------------------------------------------------- #


def png_to_escpos(png: bytes, *, cut: bool = True) -> Rendered:
	"""Pack a bitmap into `GS v 0` raster commands.

	The image is thresholded rather than dithered. Dithering is right for
	photographs and wrong for text: it turns the thin strokes Arabic is mostly
	made of into scattered dots, and on 203 dpi paper that reads as a smudge.
	"""
	from PIL import Image

	image = Image.open(io.BytesIO(png))

	# White is what the paper already is; the alpha channel has to be flattened
	# onto it or transparent areas threshold to black and the whole ticket
	# prints as a solid rectangle.
	if image.mode in ("RGBA", "LA", "P"):
		image = image.convert("RGBA")
		backdrop = Image.new("RGBA", image.size, (255, 255, 255, 255))
		image = Image.alpha_composite(backdrop, image)

	image = image.convert("L").point(lambda value: 0 if value < INK_THRESHOLD else 255, mode="1")

	width, height = image.size
	width_bytes = (width + 7) // 8
	# Pad the row to a byte boundary; the padding is white, so it prints nothing.
	padded_width = width_bytes * 8
	if padded_width != width:
		padded = Image.new("1", (padded_width, height), 1)
		padded.paste(image, (0, 0))
		image = padded

	# `tobytes()` gives 1 for white; ESC/POS wants 1 for a fired dot.
	raw = bytes(~byte & 0xFF for byte in image.tobytes())

	out = bytearray(INIT)
	for top in range(0, height, BAND_ROWS):
		rows = min(BAND_ROWS, height - top)
		band = raw[top * width_bytes : (top + rows) * width_bytes]
		out += GS + b"v0" + bytes([0])
		out += bytes([width_bytes & 0xFF, width_bytes >> 8])
		out += bytes([rows & 0xFF, rows >> 8])
		out += band

	if cut:
		out += FEED_AND_CUT

	return Rendered(payload=bytes(out), width_dots=width, height_dots=height)


# --------------------------------------------------------------------------- #
# 5. Queue it
# --------------------------------------------------------------------------- #


def queue(
	*,
	printer: str,
	job_type: str,
	rendered: Rendered,
	copies: int = 1,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	retry_of: str | None = None,
) -> str:
	"""Put a finished job where its agent will find it."""
	agent = frappe.db.get_value("POS Printer", printer, "print_agent")
	if not agent:
		frappe.throw(
			_("{0} has no print agent, so nothing can reach it.").format(printer),
		)

	job = frappe.get_doc(
		{
			"doctype": "POS Print Job",
			"printer": printer,
			"agent": agent,
			"job_type": job_type,
			"copies": copies or 1,
			"status": "queued",
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"retry_of": retry_of,
			"payload": base64.b64encode(rendered.payload).decode("ascii"),
			"payload_bytes": len(rendered.payload),
		}
	)
	job.insert(ignore_permissions=True)

	return job.name


# --------------------------------------------------------------------------- #
# The whole way through
# --------------------------------------------------------------------------- #


def print_document(
	*,
	job_type: str,
	printer: str,
	context: dict,
	template: str | None = None,
	copies: int = 1,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> str:
	"""Render a document and queue it for its printer. Returns the job name."""
	printer_doc = frappe.get_cached_doc("POS Printer", printer)
	if not printer_doc.is_active:
		frappe.throw(_("{0} is switched off.").format(printer_doc.title))

	template_name = resolve_template(
		job_type,
		paper_width=printer_doc.paper_width,
		branch=printer_doc.branch,
		explicit=template,
	)

	html = render_html(template_name, context)
	png = html_to_png(html, width_dots=PAPER_DOTS[printer_doc.paper_width])
	rendered = png_to_escpos(png, cut=bool(printer_doc.cut_after_print))

	return queue(
		printer=printer,
		job_type=job_type,
		rendered=rendered,
		copies=copies,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
	)


def drawer_kick(pin: str | int = 2) -> bytes:
	"""`ESC p` — the pulse that throws the cash drawer's latch.

	The drawer is not a device we talk to. It is a solenoid wired to a socket on
	the back of the receipt printer, and the printer fires it when it sees these
	five bytes. That is why this needs nothing from the agent: the agent already
	sends whatever bytes a job carries, and a drawer job is just a very short
	one (`D-093`).

	`m` selects which of the two pins on that socket is pulsed. Almost every
	drawer is on pin 2; some Star hardware is wired to pin 5, and a drawer on
	the wrong pin simply never opens, with nothing anywhere to say why — which
	is what `POS Printer.cash_drawer_pin` exists to fix.
	"""
	return ESC + b"p" + bytes([0 if str(pin) == "2" else 1, DRAWER_ON, DRAWER_OFF])


def open_drawer(pos_profile: str, *, reason: str) -> str | None:
	"""Open the till's cash drawer. Returns the job, or None.

	Never raises, for the reason every other entry point here does not: this is
	called from taking a payment and from opening a shift, and a drawer that
	will not open must not stop either.
	"""
	try:
		printer = _cashier_printer(pos_profile)
		if not printer:
			return None

		doc = frappe.get_cached_doc("POS Printer", printer)
		if not doc.is_active:
			return None

		payload = drawer_kick(doc.cash_drawer_pin or 2)
		return queue(
			printer=printer,
			job_type="drawer",
			rendered=Rendered(payload=payload, width_dots=0, height_dots=0),
			reference_doctype="POS Profile",
			reference_name=pos_profile,
		)
	except Exception:
		frappe.log_error(f"Could not open the drawer for {pos_profile} ({reason})", "RPOS printing")
		return None


def enqueue_print(method: str, **kwargs) -> None:
	"""Run a print off the request that caused it.

	Rendering costs about 300 ms, measured, and a kitchen send hits three
	stations — a second of a cashier's time, on every order, spent on something
	they are not waiting for. The agent polls every two seconds anyway, so
	nothing reaches paper later for having been queued.

	`enqueue_after_commit` is not optional: the worker is a separate connection,
	and without it the render can start before the ticket it is rendering has
	been committed, and fail on a document that certainly exists.
	"""
	try:
		frappe.enqueue(
			f"restaurant_pos.utils.printing.{method}",
			queue="short",
			enqueue_after_commit=True,
			**kwargs,
		)
	except Exception:
		# Redis down takes the queue with it, and `frappe.enqueue` raises. That
		# must not travel: it reached this module through `send_to_kitchen`, so
		# an unreachable queue was failing the *order* — no ticket, no sale, over
		# a printer. Found by running a real order, not by a test.
		#
		# Printing inline instead of giving up. It costs the caller ~300 ms,
		# which is the whole reason this function exists; but a slow ticket is a
		# ticket, and the alternative is a kitchen that silently gets nothing.
		frappe.log_error(f"print queue unreachable; running {method} inline", "RPOS printing")
		globals()[method](**kwargs)


def print_kot(kot_name: str, *, force: bool = False) -> str | None:
	"""Send one kitchen ticket to its station's printer (`FR-6.3`, `BR-070`).

	Never raises. A printer that is unplugged, a template with a typo, a
	renderer that is missing — none of those may stop an order reaching the
	kitchen screen or the customer being charged. The failure is recorded and
	the till carries on, because a restaurant with a broken printer still has to
	serve lunch.

	Returns the job, or None when nothing was queued.
	"""
	try:
		kot = frappe.get_doc("Kitchen Order Ticket", kot_name)
		center = frappe.get_cached_doc("Production Center", kot.production_center)
		if not force and not center.auto_print_on_send:
			# Nobody asked for paper. The ticket is on the station's screen and
			# `pending` is the truth: not printed, and not failed either.
			return None

		# BR-070 level 7: a station with no printer of its own falls to the
		# cashier's, which is the one printer somebody is standing next to.
		profile = frappe.db.get_value("Restaurant Order", kot.restaurant_order, "pos_profile")
		printer = center.printer or _cashier_printer(profile)
		if not printer:
			_mark_kot_failed(kot_name)
			return None

		return print_document(
			job_type="kot",
			printer=printer,
			context=kot_context(kot, center),
			reference_doctype="Kitchen Order Ticket",
			reference_name=kot.name,
		)
	except Exception:
		frappe.log_error(f"KOT {kot_name} could not be queued", "RPOS printing")
		_mark_kot_failed(kot_name)
		return None


def kot_context(kot, center) -> dict:
	"""What the kitchen ticket needs, in the words a cook reads.

	The document stores links — `production_center` is `PC-001`, `table` is
	`TBL-SEC-Riyadh-001-019` — and a cook needs "المشاوي" and "19". The first
	real ticket printed both ids, and the table's was long enough to widen the
	page and shear the item names off the right edge of the roll.
	"""
	return {
		"doc": kot,
		"center": center,
		"station": center.title_ar or center.title or kot.production_center,
		"table_number": frappe.db.get_value("Restaurant Table", kot.table, "table_number")
		if kot.table
		else None,
	}


def _mark_kot_failed(kot_name: str) -> None:
	"""A station that asked for paper and got none says so.

	Not left at `pending`: pending means nobody has printed it *yet*, and a
	ticket that will never print while wearing that label is the failure the
	kitchen finds out about when a customer asks where the food is.
	"""
	frappe.db.set_value("Kitchen Order Ticket", kot_name, "print_status", "failed", update_modified=0)


def print_receipt(invoice_name: str, *, order_name: str | None = None) -> str | None:
	"""Put the customer's receipt on the cashier's printer (`FR-7.5`).

	Never raises, for the same reason `print_kot` does not: the money has
	already moved. A receipt that cannot be produced is a complaint; a payment
	that rolls back because of a printer is a fraud investigation.

	Returns the job, or None when nothing was queued.
	"""
	# The whole body is guarded, not just the render. Reading a field that was
	# renamed, a Company that was deleted, a printer someone unlinked — every one
	# of those is a lookup, and a lookup that raises here would undo a payment
	# that has already been taken.
	try:
		invoice = frappe.get_doc("Sales Invoice", invoice_name)
		order = _receipt_order(order_name)

		printer = (order.default_printer if order else None) or frappe.db.get_value(
			"POS Profile", invoice.pos_profile, "default_printer"
		)
		if not printer:
			return None

		return print_document(
			job_type="customer_receipt",
			printer=printer,
			context=receipt_context(invoice, order),
			reference_doctype="Sales Invoice",
			reference_name=invoice.name,
		)
	except Exception:
		frappe.log_error(f"Receipt for {invoice_name} could not be queued", "RPOS printing")
		return None


def receipt_context(invoice, order=None) -> dict:
	"""Everything the customer's receipt is rendered from.

	Named and public so the same context can be built for a preview or a
	reprint. A second way to assemble a receipt is how two receipts for one sale
	start to differ.
	"""
	from restaurant_pos.utils import zatca

	return {
		"doc": invoice,
		"order": order or frappe._dict(),
		"company": frappe.get_cached_doc("Company", invoice.company),
		"branch": frappe.get_cached_doc("Branch", order.branch) if order and order.branch else None,
		# FR-7.5 — ZATCA Phase 1. Local arithmetic, no integration (`D-092`).
		"zatca_qr": zatca.invoice_qr(invoice),
	}


def _receipt_order(order_name: str | None):
	"""What the receipt needs from the order, in the words the template uses.

	`Restaurant Order` stores links — `order_type`, `cashier` — and the receipt
	shows names. Resolving them here keeps the template free of joins, and keeps
	a renamed field from being something an administrator has to know about.
	"""
	if not order_name:
		return None

	order = frappe.db.get_value(
		"Restaurant Order",
		order_name,
		["name", "daily_number", "call_name", "table", "order_type", "cashier", "branch", "pos_profile"],
		as_dict=True,
	)
	if not order:
		return None

	order.order_type_title = (
		frappe.db.get_value("Restaurant Order Type", order.order_type, "title_ar")
		or frappe.db.get_value("Restaurant Order Type", order.order_type, "title")
		or order.order_type
	)
	order.cashier_name = frappe.db.get_value("User", order.cashier, "full_name") or order.cashier
	order.default_printer = _cashier_printer(order.pos_profile)

	return order


def _cashier_printer(pos_profile: str | None) -> str | None:
	return frappe.db.get_value("POS Profile", pos_profile, "default_printer") if pos_profile else None


def fall_back(job_name: str) -> str | None:
	"""Re-queue a failed job on the fallback printer (`BR-072`).

	The bytes are reused rather than rendered again. A receipt that comes out of
	the second printer differing from the first — a later timestamp, a price
	edited in between — is the kind of discrepancy nobody can explain afterwards.

	Returns the new job, or None when there is nowhere else to send it.
	"""
	job = frappe.get_doc("POS Print Job", job_name)
	fallback = frappe.db.get_value("POS Printer", job.printer, "fallback_printer")
	if not fallback or job.retry_of:
		# One hop only. A fallback chain that loops back prints the same ticket
		# until somebody notices the paper is gone.
		return None

	if not frappe.db.get_value("POS Printer", fallback, "is_active"):
		return None

	agent = frappe.db.get_value("POS Printer", fallback, "print_agent")
	if not agent:
		return None

	retry = frappe.get_doc(
		{
			"doctype": "POS Print Job",
			"printer": fallback,
			"agent": agent,
			"job_type": job.job_type,
			"copies": job.copies,
			"status": "queued",
			"reference_doctype": job.reference_doctype,
			"reference_name": job.reference_name,
			"retry_of": job.name,
			"payload": job.payload,
			"payload_bytes": job.payload_bytes,
		}
	)
	retry.insert(ignore_permissions=True)

	return retry.name


#: How long a finished job keeps the bytes it printed.
#:
#: The payload is a bitmap in base64 — about 15 KB for an 80mm receipt. A busy
#: branch prints a few hundred a day, so keeping them forever is a gigabyte a
#: year of data whose only use is a reprint nobody asks for a week later. The
#: **row** stays: what printed, where, and whether it worked is history worth
#: having. Only the bytes go.
PAYLOAD_DAYS = 7

#: How long the row itself stays.
JOB_DAYS = 90


def prune_jobs() -> None:
	"""Daily: drop old payloads, then old rows (`D-085`).

	Scheduled rather than left to grow. A queue table nobody prunes is a disk
	that fills on a Friday night, and the first symptom is a till that cannot
	write an invoice.
	"""
	payload_cutoff = add_days(nowdate(), -PAYLOAD_DAYS)
	stale = frappe.get_all(
		"POS Print Job",
		filters={
			"status": ("in", ["printed", "failed"]),
			"creation": ("<", payload_cutoff),
			"payload": ("is", "set"),
		},
		pluck="name",
		limit=5000,
	)
	for name in stale:
		frappe.db.set_value("POS Print Job", name, "payload", None, update_modified=False)

	frappe.db.delete(
		"POS Print Job",
		{
			"status": ("in", ["printed", "failed"]),
			"creation": ("<", add_days(nowdate(), -JOB_DAYS)),
		},
	)


def settle(job_name: str, *, printed: bool, error: str | None = None) -> None:
	"""Record what the agent reported, and try the fallback if it failed."""
	job = frappe.get_doc("POS Print Job", job_name)
	job.db_set(
		{
			"status": "printed" if printed else "failed",
			"printed_at": now_datetime() if printed else None,
			"error": None if printed else (error or "")[:500],
		},
		update_modified=False,
	)

	# A kitchen ticket says whether it reached the kitchen; the job says whether
	# bytes went down a wire. Two questions, but **one answer** — the ticket
	# reflects its job rather than keeping a second opinion that could disagree
	# with it (CLAUDE.md §5.5).
	if job.reference_doctype == "Kitchen Order Ticket" and frappe.db.exists(
		"Kitchen Order Ticket", job.reference_name
	):
		frappe.db.set_value(
			"Kitchen Order Ticket",
			job.reference_name,
			{
				"print_status": "printed" if printed else "failed",
				"printed_at": job.printed_at,
				"printer_used": job.printer,
			},
			update_modified=False,
		)

	if not printed:
		fall_back(job_name)

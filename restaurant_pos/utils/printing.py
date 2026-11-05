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
import pathlib
import subprocess
from dataclasses import dataclass

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, cint, flt, now_datetime, nowdate

from restaurant_pos.utils.sale_doc import SALE

#: Printable width in dots, by paper size, at the 203 dpi every one of these
#: printers uses. The paper is wider than the print head can reach — 80mm paper
#: prints 72mm — which is why these are not the millimetre figures times eight.
PAPER_DOTS = {
	"58mm": 384,
	"76mm": 420,
	"80mm": 576,
}

#: What a 180 dpi head reaches on 80mm paper — Epson's TM-T70 among them. Not
#: every printer is 203 dpi, and one that is not drops the right of a receipt
#: drawn at 576 (`D-215`).
HEAD_DOTS_180_DPI = 512


def print_dots(printer_doc) -> int:
	"""How wide to draw for this printer: what its head reaches when that was
	measured and set (`D-215`), otherwise what its paper implies."""
	return cint(printer_doc.get("print_width_dots")) or PAPER_DOTS[printer_doc.paper_width]


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

	An explicit template wins — the customer receipt's is chosen on the POS
	Profile (`D-214`). Failing that a template for this branch; failing that the
	shipped default. The
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
		frappe.log_error(title="RPOS printing: wkhtmltoimage failed", message=detail)
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
	branch: str | None,
	job_type: str,
	rendered: Rendered,
	copies: int = 1,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	retry_of: str | None = None,
) -> str:
	"""Put a finished job where its agent will find it.

	``branch`` is the branch of what is being printed, and it is **required**
	(`D-363`): the last check before paper, whatever path chose the printer. A
	caller that does not know its branch has to say so with ``None``.
	"""
	from restaurant_pos.utils.printer_branch import assert_in_branch

	assert_in_branch(printer, branch, used_by=reference_name or job_type)

	terminal = requesting_terminal()
	if terminal and _reaches(terminal, frappe.get_cached_doc("POS Printer", printer), branch):
		# Bytes already made — a drawer kick: nothing for the till to draw.
		return _hand_to_till(
			terminal,
			printer=printer,
			branch=branch,
			job_type=job_type,
			copies=copies,
			reference_doctype=reference_doctype,
			reference_name=reference_name,
			paper={"raw": base64.b64encode(rendered.payload).decode("ascii")},
		)

	agent = frappe.db.get_value("POS Printer", printer, "print_agent")
	if not agent:
		# Required on the form (`D-419`); only a printer saved before that rule
		# lands here. Raised into a worker — a printer the till could not reach,
		# drawn off the request — it reached nobody, so the ticket says it
		# failed and the bell rings, as for any ticket that will not print.
		if reference_doctype == "Kitchen Order Ticket" and reference_name:
			mark_kot_failed(reference_name)
		frappe.throw(
			_("{0} has no print agent, so nothing can reach it.").format(printer),
		)

	if reference_name and not retry_of and job_type in ONE_COPY_WAITING:
		cancel_waiting(reference_doctype, reference_name, job_type)

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


#: The papers whose second copy replaces the first (`D-405`): the same ticket or
#: the same receipt asked for again. Not a drawer kick or a shift report — those
#: share a reference (the terminal) without being the same paper, and an X
#: report must not cancel the Z queued behind it.
ONE_COPY_WAITING = frozenset({"kot", "customer_receipt"})


def cancel_waiting(reference_doctype: str | None, reference_name: str, job_type: str) -> list[str]:
	"""A reprint replaces the copy nobody has taken yet (`D-405`).

	Without this, an agent that comes back after the cashier reprinted prints
	both. Read under the same row lock `claim` takes, so a cancel and a claim at
	the same instant cannot both win: whichever locks second sees the other's
	answer. **A job already taken is left alone** — it may be on the roll or in
	the Windows queue, and no row written here can pull it back; the bell says
	"it may have printed" and the cashier decides.
	"""
	waiting = frappe.get_all(
		"POS Print Job",
		filters={
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"job_type": job_type,
			"status": "queued",
			# A till hands its paper over the moment it has it: "queued" there only
			# means the agent has not reported yet, and it may be printing (`D-415`).
			"is_direct": 0,
		},
		pluck="name",
	)
	cancelled = []
	for name in waiting:
		if frappe.db.get_value("POS Print Job", name, "status", for_update=True) == "queued":
			frappe.db.set_value(
				"POS Print Job",
				name,
				{"status": "cancelled", "error": "Replaced by a reprint before any agent took it."},
				update_modified=False,
			)
			cancelled.append(name)
	return cancelled


# --------------------------------------------------------------------------- #
# The whole way through
# --------------------------------------------------------------------------- #


def print_document(
	*,
	job_type: str,
	printer: str,
	branch: str | None,
	context: dict,
	template: str | None = None,
	copies: int = 1,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> str:
	"""Render a document and queue it for its printer. Returns the job name.

	**Drawn by the till, where the till asked and can reach the printer** (`D-415`):
	the HTML goes back in the till's own response, and the browser draws it and
	hands it to its agent. The server's drawing — about half a second a page,
	measured on the user's site — is spent only on paper no till will draw.
	"""
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

	terminal = requesting_terminal()
	if terminal and _reaches(terminal, printer_doc, branch):
		return _hand_to_till(
			terminal,
			printer=printer,
			branch=branch,
			job_type=job_type,
			copies=copies,
			reference_doctype=reference_doctype,
			reference_name=reference_name,
			paper={"html": html, "width": print_dots(printer_doc), "cut": bool(printer_doc.cut_after_print)},
		)
	if terminal:
		# Running in the till's request (see `enqueue_print`), for a printer its
		# agent cannot reach: drawn off the request, as before direct printing.
		frappe.enqueue(
			"restaurant_pos.utils.printing.render_and_queue",
			queue="short",
			enqueue_after_commit=True,
			html=html,
			printer=printer,
			branch=branch,
			job_type=job_type,
			copies=copies,
			reference_doctype=reference_doctype,
			reference_name=reference_name,
		)
		return None

	return render_and_queue(
		html=html,
		printer=printer,
		branch=branch,
		job_type=job_type,
		copies=copies,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
	)


def render_and_queue(
	*,
	html: str,
	printer: str,
	branch: str | None,
	job_type: str,
	copies: int = 1,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> str:
	"""The server's own drawing: HTML to bitmap to ESC/POS, queued for the agent."""
	printer_doc = frappe.get_cached_doc("POS Printer", printer)
	png = html_to_png(html, width_dots=print_dots(printer_doc))
	rendered = png_to_escpos(png, cut=bool(printer_doc.cut_after_print))

	return queue(
		printer=printer,
		branch=branch,
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
			branch=_branch_of_profile(pos_profile),
			job_type="drawer",
			rendered=Rendered(payload=payload, width_dots=0, height_dots=0),
			reference_doctype="POS Profile",
			reference_name=pos_profile,
		)
	except Exception:
		frappe.log_error(
			title=f"Could not open the drawer for {pos_profile} ({reason})", message=frappe.get_traceback()
		)
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

	**Run in the request when a direct till asked** (`D-415`): its paper is only
	HTML, milliseconds to make, and it has to be in that request's response for
	the till to draw it. Anything the till cannot reach is still drawn off the
	request (`print_document`).
	"""
	if requesting_terminal():
		globals()[method](**kwargs)
		return

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
		frappe.log_error(
			title=f"print queue unreachable; running {method} inline", message=frappe.get_traceback()
		)
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
		from restaurant_pos.utils.kitchen import prints_on_send

		kot = frappe.get_doc("Kitchen Order Ticket", kot_name)
		center = (
			frappe.get_cached_doc("Production Center", kot.production_center)
			if kot.production_center
			else None
		)
		profile, branch = frappe.db.get_value(
			"Restaurant Order", kot.restaurant_order, ["pos_profile", "branch"]
		) or (None, None)
		if not force and not prints_on_send(kot.production_center, branch):
			# Nobody asked for paper. The ticket is on the station's screen and
			# `pending` is the truth: not printed, and not failed either.
			return None

		printer = kot_printer(kot.production_center, profile)
		if not printer:
			mark_kot_failed(kot_name)
			return None

		return print_document(
			job_type="kot",
			printer=printer,
			branch=branch,
			context=kot_context(kot, center),
			reference_doctype="Kitchen Order Ticket",
			reference_name=kot.name,
		)
	except Exception:
		frappe.log_error(title=f"KOT {kot_name} could not be queued", message=frappe.get_traceback())
		mark_kot_failed(kot_name)
		return None


def queue_receipt(invoice_name: str, *, order_name: str | None, pos_profile: str | None) -> None:
	"""The customer's receipt, queued only for a terminal that has a printer (`D-364`).

	The receipt is printed on every sale where there is paper; where there is
	none, a job that will only find that out is a job the worker does for
	nothing — two a sale in the load test, in front of the day's posting.
	"""
	if receipt_printer(pos_profile, order_name):
		enqueue_print("print_receipt", invoice_name=invoice_name, order_name=order_name)


def queue_report(pos_profile: str | None, **kwargs) -> None:
	"""An X or Z report, queued only for a terminal that has a printer (`D-364`)."""
	if _cashier_printer(pos_profile):
		enqueue_print("print_shift_report", pos_profile=pos_profile, **kwargs)


def kot_printer(production_center: str | None, pos_profile: str | None) -> str | None:
	"""Which printer a ticket comes out of, if any: its station's own (`D-396`).

	Never the cashier's by itself. `D-300` sent a station with no printer, or
	no station at all, there; the owner's rule is that a ticket prints where
	the manager routed it — a station on the cashier's printer, if that is the
	place. Asked before the job is queued (`D-364`) and by the job itself, so
	the two cannot disagree.
	"""
	if not production_center:
		return None
	return frappe.get_cached_doc("Production Center", production_center).printer


def _modifier_lines(stored) -> list[str]:
	"""A ticket line's add-ons, as the words the cook reads (`D-390`).

	Worked out here, not in the template: the template called
	`frappe.parse_json`, which the sandboxed renderer does not offer, so every
	ticket carrying an add-on failed to print — and it read `title` from rows
	that store `option` / `option_ar`, so it would have printed a dict.
	"""
	if not stored:
		return []
	rows = frappe.parse_json(stored) if isinstance(stored, str) else stored
	lines = []
	for row in rows or []:
		if isinstance(row, dict):
			name = row.get("option_ar") or row.get("option") or row.get("item_name") or row.get("title")
			if name:
				lines.append(name)
		elif row:
			lines.append(str(row))
	return lines


def kot_context(kot, center) -> dict:
	"""What the kitchen ticket needs, in the words a cook reads.

	The document stores links — `production_center` is `PC-001`, `table` is
	`TBL-SEC-Riyadh-001-019` — and a cook needs "المشاوي" and "19". The first
	real ticket printed both ids, and the table's was long enough to widen the
	page and shear the item names off the right edge of the roll.
	"""
	for item in kot.items or []:
		item.modifier_lines = _modifier_lines(item.modifiers)
	return {
		"doc": kot,
		"center": center,
		"station": (center.title_ar or center.title or kot.production_center)
		if center
		else _("Cashier printer"),
		"table_number": frappe.db.get_value("Restaurant Table", kot.table, "table_number")
		if kot.table
		else None,
	}


def mark_kot_failed(kot_name: str) -> None:
	"""A station that asked for paper and got none says so.

	Not left at `pending`: pending means nobody has printed it *yet*, and a
	ticket that will never print while wearing that label is the failure the
	kitchen finds out about when a customer asks where the food is.
	"""
	frappe.db.set_value(
		"Kitchen Order Ticket",
		kot_name,
		{"print_status": "failed", "print_failed_at": now_datetime()},
		update_modified=0,
	)


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
		invoice = frappe.get_doc(SALE, invoice_name)
		order = _receipt_order(order_name)

		printer = receipt_printer(invoice.pos_profile, order_name)
		if not printer:
			return None

		return print_document(
			job_type="customer_receipt",
			printer=printer,
			branch=invoice.get("rpos_branch") or _branch_of_profile(invoice.pos_profile),
			context=receipt_context(invoice, order),
			# D-214 — the terminal's own choice, sent as it is: a design for other
			# paper prints at this printer's width, and the paper is the judge.
			template=frappe.db.get_value("POS Profile", invoice.pos_profile, "receipt_template"),
			reference_doctype=SALE,
			reference_name=invoice.name,
		)
	except Exception:
		frappe.log_error(
			title=f"Receipt for {invoice_name} could not be queued", message=frappe.get_traceback()
		)
		return None


def print_shift_report(
	*, pos_profile: str, opening_entry: str | None = None, shift: str | None = None
) -> str | None:
	"""The financial report on the terminal's printer — a drawer's or a day's (FR-8.3, `D-219`).

	**X or Z is read, not passed.** Z is what a closed drawer or day prints, X
	what an open one does; a caller that could say "Z" over a drawer still
	taking money would print a final report that is not final.

	Never raises, for the reason the receipt does not: Z is printed from a close,
	and a close that has counted the money must not be undone by a printer.

	Returns the job, or None when nothing was queued.
	"""
	try:
		printer = _cashier_printer(pos_profile)
		if not printer:
			return None

		return print_document(
			job_type="shift_report",
			printer=printer,
			branch=_branch_of_profile(pos_profile),
			context=shift_report_context(pos_profile=pos_profile, opening_entry=opening_entry, shift=shift),
			reference_doctype="POS Opening Entry" if opening_entry else "Restaurant Shift",
			reference_name=opening_entry or shift,
		)
	except Exception:
		frappe.log_error(
			title=f"Shift report for {opening_entry or shift} could not be queued",
			message=frappe.get_traceback(),
		)
		return None


def shift_report_context(
	*, pos_profile: str, opening_entry: str | None = None, shift: str | None = None
) -> dict:
	"""Everything the financial report is drawn from, for a drawer or a day (`D-219`).

	Named and public for the reason `receipt_context` is: a second way to put this
	together is how the paper and the screen start to disagree.
	"""
	from restaurant_pos.utils import shift as shifts

	if opening_entry:
		report = shifts.summarise_till(opening_entry)
		entry = frappe.db.get_value(
			"POS Opening Entry", opening_entry, ["status", "user", "period_start_date"], as_dict=True
		)
		final = entry.status == "Closed"
		who = frappe.db.get_value("User", entry.user, "full_name") or entry.user
		opened = entry.period_start_date
		ended = frappe.db.get_value(
			"POS Closing Entry", {"pos_opening_entry": opening_entry, "docstatus": 1}, "period_end_date"
		)
		# A drawer still open has been counted by nobody: expected, and no count.
		drawers = report.get("tills") or [
			{
				"name": who,
				"opening": _opening(report),
				"expected": report["till_expected"],
				"counted": None,
				"difference": None,
			}
		]
	else:
		report = shifts.summarise(shift)
		day = frappe.db.get_value(
			"Restaurant Shift", shift, ["status", "opened_at", "closed_at"], as_dict=True
		)
		final = day.status == "closed"
		who = None
		opened, ended = day.opened_at, day.closed_at
		drawers = report.get("tills") or []

	company = frappe.get_cached_doc("Company", frappe.db.get_value("POS Profile", pos_profile, "company"))
	return {
		"report": report,
		"kind": "Z" if final else "X",
		"company": company,
		"branch": report.get("branch"),
		"logo": logo_url(company),
		"who": who,
		"drawers": drawers,
		"opened": _stamp(opened),
		"closed": _stamp(ended or now_datetime()),
		"printed_at": _stamp(now_datetime()),
	}


def _opening(report: dict) -> float:
	return sum(flt(row["opening"]) for row in report["by_method"] if row["kind"] == "till")


def _stamp(moment) -> str:
	return frappe.utils.format_datetime(moment, "dd/MM/yyyy HH:mm") if moment else ""


def receipt_printer(pos_profile: str | None, order_name: str | None = None) -> str | None:
	"""Which printer a receipt for this bill would come out of, if any.

	Named and shared because **two callers need the same answer for opposite
	reasons** (`CLAUDE.md` §5.5): `print_receipt` asks so it can give up quietly
	— the money has moved and a printer must not undo that — and the reprint
	endpoint asks so it can refuse *loudly*, before telling a cashier their
	paper is on its way to a terminal that has no printer at all (`D-148`).

	The order's own printer wins: a bill rung up on the terrace prints where the
	terrace prints, whatever the profile's default says.
	"""
	order = _receipt_order(order_name)
	return (order.default_printer if order else None) or frappe.db.get_value(
		"POS Profile", pos_profile, "default_printer"
	)


def receipt_context(invoice, order=None) -> dict:
	"""Everything the customer's receipt is rendered from.

	Named and public so the same context can be built for a preview or a
	reprint. A second way to assemble a receipt is how two receipts for one sale
	start to differ.
	"""
	from restaurant_pos.utils import zatca

	company = frappe.get_cached_doc("Company", invoice.company)

	return {
		"doc": invoice,
		"order": order or frappe._dict(),
		"company": company,
		"branch": frappe.get_cached_doc("Branch", order.branch) if order and order.branch else None,
		"logo": logo_url(company),
		# Whether the prices printed beside the items already contain the tax.
		# Read from the invoice rather than from a setting, so the notice on the
		# paper can never disagree with the arithmetic above it (`D-091`).
		"tax_inclusive": any(tax.included_in_print_rate for tax in invoice.taxes),
		# FR-7.5 — ZATCA Phase 1. Local arithmetic, no integration (`D-092`).
		"zatca_qr": zatca.invoice_qr(invoice),
		"loyalty": _receipt_loyalty(invoice, order),
	}


def _receipt_loyalty(invoice, order) -> dict | None:
	"""Points on this receipt: what the bill spent and earned, and what is left.

	**A sale only** (`D-189`). A credit note's receipt reverses money, and the
	sale's points printed under it would tell the guest they earned something on
	a refund. And nothing at all on a bill that neither spent nor earned — a
	walk-in's coffee does not need a loyalty block.

	The balance is the balance **when this prints**, which on a reprint weeks
	later is that day's — still a true statement of what the guest holds.
	"""
	if invoice.get("is_return") or not order or not order.get("customer"):
		return None

	spent = cint(order.get("loyalty_points"))
	earned = cint(order.get("loyalty_points_earned"))
	if not spent and not earned:
		return None

	from restaurant_pos.utils import loyalty

	program = frappe.db.get_value("Customer", order.customer, "loyalty_program")
	return {
		"spent": spent,
		"amount": flt(order.get("loyalty_amount")),
		"earned": earned,
		"balance": loyalty.balance(order.customer, program) if program else 0,
	}


def logo_url(company) -> str | None:
	"""The company logo as something wkhtmltoimage can actually open.

	It renders with `--enable-local-file-access` and no network, so the
	`/files/...` URL stored on the Company fetches nothing at all — the receipt
	prints with a broken-image box where the logo should be. It needs the file
	on disk.

	Returns nothing when no logo is set or the file has been deleted, and the
	template simply omits it: a missing logo must not cost a customer a receipt.
	"""
	url = (company.get("company_logo") or "").strip()
	if not url.startswith("/files/"):
		return None

	path = pathlib.Path(frappe.get_site_path("public", url.lstrip("/")))
	return path.as_uri() if path.exists() else None


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
		[
			"name",
			"daily_number",
			"call_name",
			"table",
			"order_type",
			"cashier",
			"branch",
			"pos_profile",
			# D-189 — the receipt's points block.
			"customer",
			"loyalty_points",
			"loyalty_amount",
			"loyalty_points_earned",
		],
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
	# The number a customer would say out loud, not the document id. Printing
	# the id once widened an RTL ticket enough to shear the item names off the
	# roll (`D-087`); it is also of no use to anybody holding the receipt.
	order.table_number = (
		frappe.db.get_value("Restaurant Table", order.table, "table_number") if order.table else None
	)

	return order


def _branch_of_profile(pos_profile: str | None) -> str | None:
	from restaurant_pos.utils.order import branch_of_profile

	return branch_of_profile(pos_profile) if pos_profile else None


def _cashier_printer(pos_profile: str | None) -> str | None:
	return frappe.db.get_value("POS Profile", pos_profile, "default_printer") if pos_profile else None


def backup_printer(printer: str) -> str | None:
	"""Where a failure on ``printer`` may go (`BR-072`), or None."""
	fallback = frappe.db.get_value("POS Printer", printer, "fallback_printer")
	if not fallback or not frappe.db.get_value("POS Printer", fallback, "is_active"):
		return None

	# D-363 — never into another branch, even from a fallback saved before the rule.
	if frappe.db.get_value("POS Printer", fallback, "branch") != frappe.db.get_value(
		"POS Printer", printer, "branch"
	):
		return None

	return fallback if frappe.db.get_value("POS Printer", fallback, "print_agent") else None


def fall_back(job_name: str) -> str | None:
	"""Re-queue a failed job on the fallback printer (`BR-072`).

	The paper is reused rather than made again. A receipt that comes out of
	the second printer differing from the first — a later timestamp, a price
	edited in between — is the kind of discrepancy nobody can explain afterwards.

	**A till that reaches the backup sends it there itself** (`D-417`): it holds
	the paper and hears "nothing left" from its agent at once. The row is made
	here, in the agent's own report, under the name the till was given with the
	paper — so the switch costs no request of its own.

	Returns the new job, or None when there is nowhere else to send it — or
	nothing to send: **never an empty copy** (`D-416`). The bell rings instead.
	"""
	job = frappe.get_doc("POS Print Job", job_name)
	if job.retry_of:
		# One hop only. A fallback chain that loops back prints the same ticket
		# until somebody notices the paper is gone.
		return None

	fallback = backup_printer(job.printer)
	if not fallback:
		return None

	if job.is_direct and _agent_reaches(job.agent, frappe.get_cached_doc("POS Printer", fallback)):
		retry = frappe.get_doc(
			{
				"doctype": "POS Print Job",
				"printer": fallback,
				"agent": job.agent,
				"branch": job.branch,
				"job_type": job.job_type,
				"copies": job.copies,
				"status": "queued",
				"is_direct": 1,
				"reference_doctype": job.reference_doctype,
				"reference_name": job.reference_name,
				"retry_of": job.name,
			}
		)
		retry.insert(ignore_permissions=True, set_name=backup_job_name(job.name))
		return retry.name

	payload = _paper_for_fallback(job, fallback)
	if not payload:
		return None

	retry = frappe.get_doc(
		{
			"doctype": "POS Print Job",
			"printer": fallback,
			"agent": frappe.db.get_value("POS Printer", fallback, "print_agent"),
			"job_type": job.job_type,
			"copies": job.copies,
			"status": "queued",
			"reference_doctype": job.reference_doctype,
			"reference_name": job.reference_name,
			"retry_of": job.name,
			"payload": payload,
			"payload_bytes": len(base64.b64decode(payload)),
		}
	)
	retry.insert(ignore_permissions=True)

	return retry.name


def _paper_for_fallback(job, fallback: str) -> str | None:
	"""The paper for the backup printer, in base64, or None when there is none.

	A job the server drew carries its bytes. A job a till drew carries nothing
	(`docs/15` §5.2), so the server kept the till's paper for its shelf life
	(`_hand_to_till`) and draws that same HTML here, for the backup's width —
	the one time the server draws a till's paper, and only on a failure.
	Aloha's and Simphony's print controllers do the same: whoever decides on
	the backup holds the ticket until it is known to have printed (`D-416`).
	"""
	if job.payload:
		return job.payload
	paper = frappe.cache().get_value(_paper_key(job.name)) if job.is_direct else None
	if not paper:
		# Gone with its shelf life, or with a Redis restart: the bell asks.
		return None
	if paper.get("raw"):
		return paper["raw"]

	printer_doc = frappe.get_cached_doc("POS Printer", fallback)
	try:
		png = html_to_png(paper["html"], width_dots=print_dots(printer_doc))
	except Exception:
		# Inside the agent's report: a drawing that fails must not fail the
		# report, or the agent sends it again. The bell rings instead.
		frappe.log_error(title="RPOS: drawing a till's paper for the backup printer")
		return None
	rendered = png_to_escpos(png, cut=bool(printer_doc.cut_after_print))
	return base64.b64encode(rendered.payload).decode("ascii")


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
			"status": ("in", FINISHED),
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
			"status": ("in", FINISHED),
			"creation": ("<", add_days(nowdate(), -JOB_DAYS)),
		},
	)


#: Every state a job does not leave by itself. ``unconfirmed`` is among them: it
#: waits for a late report or for the cashier, and nothing else moves it.
FINISHED = ["printed", "failed", "unconfirmed", "cancelled"]


#: Why an agent could not print, as it reports it (agent 1.1.0, `D-403`). Said
#: in plain words on the screen; anything else is kept as the raw error only.
REASONS = frozenset(
	{"paper_out", "paused", "offline", "attention", "error", "not_found", "not_taken", "unreachable"}
)


def settle(
	job_name: str,
	*,
	printed: bool,
	error: str | None = None,
	reason: str | None = None,
	try_fallback: bool = True,
	nothing_sent: bool = False,
) -> None:
	"""Record what happened to one job (`D-405`).

	Three outcomes, and the difference between the last two is the whole point:

	- ``printed`` — the agent sent every byte. As far as anyone can know: a
	  thermal printer does not say the paper came out.
	- ``failed`` — **known** not to have printed: nothing was sent. The only
	  outcome that may go to the fallback printer.
	- ``unconfirmed`` — anything else. It may be on the roll. Nothing prints it
	  again by itself; the bell asks the cashier, who can see the printer.

	``nothing_sent`` is said by whoever knows: the agent, which counts the bytes
	across every copy, or the server for a job that expired before anyone took
	it. Not said is not known, and not known is unconfirmed.

	``try_fallback`` is off for a job that expired unprinted (`D-108`): a ticket
	too late for its own printer is too late for the backup as well.
	"""
	job = frappe.get_doc("POS Print Job", job_name)
	if job.status in ("printed", "failed", "cancelled"):
		# A report after the answer is in: an agent repeating itself, or one that
		# took a job a reprint had already replaced. Neither changes what is true —
		# and a repeated failure must not send a second copy to the backup.
		return

	late = job.status == "unconfirmed"

	status = "printed" if printed else ("failed" if nothing_sent else "unconfirmed")
	outcome = {
		"status": status,
		"printed_at": now_datetime() if printed else None,
		"error": None if printed else (error or "")[:500],
	}
	# The code reaches a site before its migrate does. Writing a column the site
	# does not have yet failed every report, so every ticket was taken back and
	# printed again every two minutes for twenty (`D-404`). The outcome is the
	# point; the reason is a nicety that waits for the migrate.
	if job.meta.has_field("reason"):
		outcome["reason"] = None if printed or reason not in REASONS else reason
	job.db_set(outcome, update_modified=False)

	# **Late is never a reason to print elsewhere.** A report that arrives after
	# the bell already asked the cashier may meet a reprint they already made.
	retry = fall_back(job_name) if status == "failed" and try_fallback and not late else None

	# A late failure tells the ticket nothing new — it has rung already, and the
	# cashier may have answered it. A late success is news: the paper is out.
	if printed or not late:
		_tell_the_ticket(job, printed=printed, on_its_way=bool(retry))


def mark_unconfirmed(job_name: str, error: str) -> None:
	"""No report came: say so, and leave the job where it is (`D-405`).

	Replaces the old "take it back and hand it out again", which printed one
	user's receipt, two kitchen tickets and a drawer kick four times each
	(`D-404`). The job stays with its agent; a report that turns up later still
	lands (`settle` takes it from ``unconfirmed``).
	"""
	if frappe.db.get_value("POS Print Job", job_name, "status", for_update=True) != "claimed":
		return
	job = frappe.get_doc("POS Print Job", job_name)
	job.db_set({"status": "unconfirmed", "error": error[:500]}, update_modified=False)
	_tell_the_ticket(job, printed=False, on_its_way=False)


def _tell_the_ticket(job, *, printed: bool, on_its_way: bool) -> None:
	"""A kitchen ticket says whether it reached the kitchen.

	The job says whether bytes went down a wire. Two questions, but **one
	answer** — the ticket reflects its job rather than keeping a second opinion
	that could disagree with it (CLAUDE.md §5.5).

	**Still `pending` while the backup has it** (`D-211`). The bell rings on
	`failed`, and ringing now would send the cashier to reprint a ticket that is
	about to come out of the backup printer — two tickets, two plates.

	**Only the newest job speaks for the ticket** (`D-405`). After a reprint, a
	late failure from the first copy must not ring for a ticket the second has
	printed. A late *success* still counts: the kitchen has the paper.
	"""
	if job.reference_doctype != "Kitchen Order Ticket" or not frappe.db.exists(
		"Kitchen Order Ticket", job.reference_name
	):
		return
	if not printed and _superseded(job):
		return

	status = "printed" if printed else ("pending" if on_its_way else "failed")
	frappe.db.set_value(
		"Kitchen Order Ticket",
		job.reference_name,
		{
			"print_status": status,
			"printed_at": now_datetime() if printed else None,
			"printer_used": job.printer,
			# `D-298` — the bell lists tickets by this, so it is written on
			# every road to `failed`: a ticket with no printer at all never
			# had a job, and a list read off the jobs missed it.
			**({"print_failed_at": now_datetime()} if status == "failed" else {}),
		},
		update_modified=False,
	)


def _superseded(job) -> bool:
	"""A later job for the same paper — a reprint, or the fallback's copy."""
	return bool(
		frappe.db.exists(
			"POS Print Job",
			{
				"reference_doctype": job.reference_doctype,
				"reference_name": job.reference_name,
				"name": ("!=", job.name),
				"creation": (">", job.creation),
				"status": ("!=", "cancelled"),
			},
		)
	)


#: A job nobody took in this long has no agent listening: agents ask every two
#: seconds, so thirty is fifteen chances missed (`D-405`).
UNTAKEN_SECONDS = 30

#: A job taken and not reported on in this long is unconfirmed (`D-405`).
#: Sixty, not thirty, because of agents already installed: one takes up to five
#: jobs at a time and waits up to ten seconds on each Windows printer, so the
#: fifth may honestly be reported fifty seconds after it was taken.
UNREPORTED_SECONDS = 60

#: How long a queued paper is still worth printing, in seconds (`D-108`, `D-412`).
#:
#: **Two minutes, for every paper.** It was twenty, and the user said what that
#: does in a real kitchen: the agent is down, the cashier calls the order through
#: by voice, the food goes out — and fifteen minutes later the ticket prints, and
#: the cook, who cannot tell it is the same order, makes it again. A receipt that
#: prints after its customer left is paper thrown away. Two minutes covers what
#: comes back by itself — an agent restarting, a Windows update, the Wi-Fi gone
#: for seconds — and is too short for any kitchen to have served the order. After
#: that the ticket is not lost: the bell already says it did not print (within a
#: minute), and the cashier reprints it or tells the kitchen.
SHELF_SECONDS = 120

#: A drawer kick lives thirty seconds (`D-412`). A drawer that did not open is
#: opened with its key; one that springs open a minute later is cash on show
#: with nobody at the till.
SHELF_SECONDS_BY_TYPE = {"drawer": 30}


def shelf_seconds(job_type: str) -> int:
	return SHELF_SECONDS_BY_TYPE.get(job_type, SHELF_SECONDS)


def sweep_jobs() -> None:
	"""Every minute: nothing waits in silence (`D-405`).

	Three questions, each an indexed read:

	1. **Taken and never reported** → ``unconfirmed``, and the bell rings. The
	   job stays with its agent and is never handed out again.
	2. **Not taken by anyone** → the ticket rings now; the job keeps waiting, so
	   an agent that comes back still prints it, unless the cashier reprinted.
	3. **Waiting past its shelf life** → dropped (`D-108`), for every agent —
	   it used to happen only when the dead agent itself asked again.

	Here and not in `claim`: an agent that stopped asking is exactly the one
	whose jobs need looking at.
	"""
	now = now_datetime()

	for name in frappe.get_all(
		"POS Print Job",
		filters={
			"status": "claimed",
			"claimed_at": ("<", add_to_date(now, seconds=-UNREPORTED_SECONDS)),
		},
		pluck="name",
	):
		mark_unconfirmed(name, "No report from the agent; it may have printed.")

	# A till hands its paper over at once, so "queued" past this means the agent
	# never reported — or the till never handed it. Either may have printed.
	for name in frappe.get_all(
		"POS Print Job",
		filters={
			"status": "queued",
			"is_direct": 1,
			"creation": ("<", add_to_date(now, seconds=-UNREPORTED_SECONDS)),
		},
		pluck="name",
	):
		mark_not_handed(name, "No report from the agent; it may have printed.")

	untaken = frappe.get_all(
		"POS Print Job",
		filters={
			"status": "queued",
			"is_direct": 0,
			"reference_doctype": "Kitchen Order Ticket",
			"creation": ("<", add_to_date(now, seconds=-UNTAKEN_SECONDS)),
		},
		pluck="reference_name",
	)
	for kot in set(untaken):
		if frappe.db.get_value("Kitchen Order Ticket", kot, "print_status") == "pending":
			mark_kot_failed(kot)

	expire_old()


def expire_old(agent: str | None = None) -> None:
	"""Drop the backlog rather than print it (`D-108`).

	An agent that was switched off all day, or a printer nobody had plugged in
	yet, comes back to a queue full of tickets whose moment has passed. Printing
	them is not catching up — it is a cook receiving twenty orders that were
	served, cancelled or paid hours ago, with no way to tell which.

	Run by every poll, before anything is handed out, so a paper past its shelf
	life never reaches an agent that comes back (`D-412`).

	Marked failed rather than deleted: "this was queued and never printed" is
	the answer to a question somebody will ask, and a row that vanished answers
	nothing. **Failed, not unconfirmed** — nobody took it, so nothing was sent.
	The fallback printer is not tried either — the same staleness applies there.
	"""
	now = now_datetime()
	shortest = min([SHELF_SECONDS, *SHELF_SECONDS_BY_TYPE.values()])
	# Not a till's paper: it went to its agent at once and is settled as
	# unconfirmed, never as "nothing sent" (`sweep_jobs`).
	filters = {"status": "queued", "is_direct": 0, "creation": ("<", add_to_date(now, seconds=-shortest))}
	if agent:
		filters["agent"] = agent
	waiting = frappe.get_all("POS Print Job", filters=filters, fields=["name", "job_type", "creation"])
	stale = [row for row in waiting if row.creation < add_to_date(now, seconds=-shelf_seconds(row.job_type))]

	for row in stale:
		# Under the claim's lock: an agent taking it this instant wins, and its
		# report is what counts.
		if frappe.db.get_value("POS Print Job", row.name, "status", for_update=True) != "queued":
			continue
		settle(
			row.name,
			printed=False,
			error=f"Not printed within {shelf_seconds(row.job_type)} seconds; too late to be useful.",
			try_fallback=False,
			nothing_sent=True,
		)

	if stale:
		frappe.log_error(f"{len(stale)} stale print jobs dropped", "RPOS printing")


# --------------------------------------------------------------------------- #
# Paper the till draws itself (`D-415`, `docs/15` §5.1 to §5.3)
# --------------------------------------------------------------------------- #

#: The header a till sends on every request, naming its terminal. Paper is
#: handed back only to a till that asked, set to print direct.
TILL_HEADER = "X-RPOS-Till"


def requesting_terminal():
	"""The terminal of the till making this request, when it prints direct.

	None outside a web request (a worker, a scheduled job, a test), from anything
	but the till (the desk sends no header), and for a terminal printing through
	the server. A forged header could only send a paper to the forger's own
	browser rather than the queue: it never prints anywhere it should not.
	"""
	if not getattr(frappe.local, "request", None):
		return None
	name = frappe.get_request_header(TILL_HEADER)
	if not name:
		return None
	from urllib.parse import unquote

	name = unquote(name)
	if not frappe.db.exists("POS Profile", name):
		return None
	terminal = frappe.get_cached_doc("POS Profile", name)
	if terminal.get("rpos_print_route") != "direct" or not terminal.get("rpos_print_agent"):
		return None
	return terminal


def _reaches(terminal, printer_doc, branch: str | None) -> bool:
	"""Whether this till's agent can put this paper on this printer.

	A network printer is reached by any agent on the restaurant's network; a
	printer on a cable only by the agent on the computer it is plugged into
	(`D-402`). And only in the till's own branch (`D-363`).
	"""
	if branch and terminal.get("rpos_branch") and terminal.rpos_branch != branch:
		return False
	return _agent_reaches(terminal.rpos_print_agent, printer_doc)


def _agent_reaches(agent: str, printer_doc) -> bool:
	return printer_doc.connection_type == "network" or printer_doc.print_agent == agent


def _hand_to_till(
	terminal,
	*,
	printer: str,
	branch: str | None,
	job_type: str,
	copies: int,
	reference_doctype: str | None,
	reference_name: str | None,
	paper: dict,
) -> str:
	"""Record the paper, and put it in this request's response for the till.

	The row is the light record of `docs/15` §5.2: no bitmap, never fetched by
	an agent (`is_direct`), settled by the agent's own report. Its agent is the
	till's, the one that will print it and report it. Read by the till from
	``rpos_papers`` beside ``message`` — every endpoint carries it, so none has
	to remember to.
	"""
	from restaurant_pos.api.printing import _connection

	job = frappe.get_doc(
		{
			"doctype": "POS Print Job",
			"printer": printer,
			"agent": terminal.rpos_print_agent,
			"branch": branch,
			"job_type": job_type,
			"copies": copies or 1,
			"status": "queued",
			"is_direct": 1,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
		}
	)
	job.insert(ignore_permissions=True)
	if reference_name and job_type in ONE_COPY_WAITING:
		# A reprint from the till replaces a copy still waiting in the queue.
		cancel_waiting(reference_doctype, reference_name, job_type)

	# In case the agent says nothing left it (`fall_back`). A backup this till
	# reaches goes with the paper, and the till sends it there itself (`D-417`);
	# one it cannot reach is the server's, which holds the paper in Redis for
	# its shelf life, not on the row (`D-416`).
	backup = backup_printer(printer)
	if backup:
		backup_doc = frappe.get_cached_doc("POS Printer", backup)
		if _agent_reaches(job.agent, backup_doc):
			paper = {
				**paper,
				"fallback": {
					"job": backup_job_name(job.name),
					"printer": _connection(backup),
					"width": print_dots(backup_doc),
					"cut": bool(backup_doc.cut_after_print),
				},
			}
		else:
			frappe.cache().set_value(_paper_key(job.name), paper, expires_in_sec=shelf_seconds(job_type))

	frappe.response.setdefault("rpos_papers", []).append(
		{"job": job.name, "printer": _connection(printer), "copies": copies or 1, **paper}
	)
	return job.name


def _paper_key(job_name: str) -> str:
	return f"rpos_till_paper:{job_name}"


def backup_job_name(job_name: str) -> str:
	"""The backup copy's name, known to the till before the copy exists (`D-417`)."""
	return f"{job_name}-b"


def mark_not_handed(job_name: str, error: str) -> None:
	"""The till could not get its paper to its agent, or heard nothing back (`D-405`).

	Unconfirmed, not failed: the till cannot tell "never arrived" from "arrived
	and the answer was lost". The agent's own report, if it comes, still lands.
	"""
	if frappe.db.get_value("POS Print Job", job_name, "status", for_update=True) != "queued":
		return
	job = frappe.get_doc("POS Print Job", job_name)
	if not job.is_direct:
		return
	job.db_set({"status": "unconfirmed", "error": (error or "")[:500]}, update_modified=False)
	_tell_the_ticket(job, printed=False, on_its_way=False)

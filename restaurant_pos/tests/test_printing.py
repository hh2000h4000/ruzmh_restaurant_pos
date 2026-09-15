# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Printing tests.

The pipeline splits at the bytes: the server renders and queues, an agent inside
the restaurant sends and reports (`D-084`). These cover both halves of that seam
and the rules that keep one ticket from becoming two plates of food.

Refs: FR-6.4, FR-7.2, FR-7.3, FR-7.5, BR-070, BR-072, D-084, D-085
"""

import base64
import io
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from restaurant_pos.api import order as order_api
from restaurant_pos.api import printing as api
from restaurant_pos.restaurant_pos.doctype.pos_print_agent import pos_print_agent
from restaurant_pos.setup import print_templates
from restaurant_pos.tests.test_order import BRANCH, ITEM, OrderTestBase, _make_cashier
from restaurant_pos.tests.test_payment import PaymentTestBase
from restaurant_pos.tests.test_returns import REASON as RETURN_REASON
from restaurant_pos.tests.test_returns import ReturnTestBase
from restaurant_pos.utils import kitchen
from restaurant_pos.utils import order as orders
from restaurant_pos.utils import printing as service
from restaurant_pos.utils import returns as service_returns


def _white_png(width: int, height: int) -> bytes:
	"""A blank bitmap of a known size, for the arithmetic tests."""
	from PIL import Image

	out = io.BytesIO()
	Image.new("1", (width, height), 1).save(out, format="PNG")
	return out.getvalue()


def _agent(title: str) -> str:
	existing = frappe.db.get_value("POS Print Agent", {"title": title, "branch": BRANCH})
	if existing:
		return existing

	return (
		frappe.get_doc({"doctype": "POS Print Agent", "title": title, "branch": BRANCH, "is_active": 1})
		.insert(ignore_permissions=True)
		.name
	)


def _printer(title: str, *, agent: str, fallback: str | None = None) -> str:
	existing = frappe.db.get_value("POS Printer", {"title": title, "branch": BRANCH})
	if existing:
		frappe.db.set_value("POS Printer", existing, "fallback_printer", fallback)
		return existing

	return (
		frappe.get_doc(
			{
				"doctype": "POS Printer",
				"title": title,
				"branch": BRANCH,
				"print_agent": agent,
				"connection_type": "network",
				"ip_address": "127.0.0.1",
				"port": 9100,
				"printer_model": "epson",
				"paper_width": "80mm",
				"print_mode": "image",
				"cut_after_print": 1,
				"is_active": 1,
				"fallback_printer": fallback,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


class PrintingTestBase(OrderTestBase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.agent = _agent("RPOS Test Agent")
		cls.backup_printer = _printer("RPOS Test Backup Printer", agent=cls.agent)
		cls.printer = _printer("RPOS Test Printer", agent=cls.agent, fallback=cls.backup_printer)
		cls.grill = frappe.db.get_value("Production Center", {"title": "RPOS Test Grill"}, "name")
		frappe.db.commit()

	def setUp(self):
		super().setUp()
		# Stated every time rather than once in setUpClass. Several tests here
		# move a printer between agents on purpose, and a test that inherits the
		# previous one's arrangement fails for a reason that is not written in it.
		frappe.db.set_value("Production Center", self.grill, "printer", self.printer)
		frappe.db.set_value("Production Center", self.grill, "auto_print_on_send", 1)
		frappe.db.set_value(
			"POS Printer",
			self.printer,
			{"print_agent": self.agent, "fallback_printer": self.backup_printer, "is_active": 1},
		)
		frappe.db.set_value("POS Printer", self.backup_printer, "print_agent", self.agent)

		# Start from an empty queue. `setUpClass` commits its printers, so jobs
		# from previous runs survive the per-test rollback — and `claim` takes
		# the oldest five, which were somebody else's. The first version of this
		# file failed on a job it never created.
		frappe.db.delete("POS Print Job", {"agent": self.agent})

	def _sent_kot(self):
		order = self._order()
		row = orders.add_item(order, item=ITEM, qty=1)
		row.production_center = self.grill
		order.save(ignore_permissions=True)

		result = kitchen.send_to_kitchen(order)
		return frappe.get_doc("Kitchen Order Ticket", result["kots_created"][0]["kot_name"])


class TestTheBytes(FrappeTestCase):
	"""The half that has no database in it."""

	def test_a_raster_command_states_the_width_in_bytes(self):
		"""`GS v 0` counts bytes across and dots down; mixing them prints noise."""
		rendered = service.png_to_escpos(_white_png(576, 10), cut=False)

		self.assertEqual(rendered.width_dots, 576)
		self.assertEqual(rendered.height_dots, 10)

		# ESC @ then GS v 0 m xL xH yL yH
		self.assertTrue(rendered.payload.startswith(service.INIT))
		header = rendered.payload[len(service.INIT) :][:8]
		self.assertEqual(header[:3], b"\x1dv0")
		self.assertEqual(header[4] | (header[5] << 8), 576 // 8)
		self.assertEqual(header[6] | (header[7] << 8), 10)

	def test_a_white_page_fires_no_dots(self):
		"""1 is white on the way in and a fired dot on the way out.

		Getting this inversion wrong prints a solid black rectangle, empties the
		roll, and looks like a hardware fault.
		"""
		rendered = service.png_to_escpos(_white_png(64, 8), cut=False)
		body = rendered.payload[len(service.INIT) + 8 :]

		self.assertEqual(set(body), {0})

	def test_a_mid_grey_stroke_still_fires_a_dot(self):
		"""D-109 — the threshold, from a real print rather than from taste.

		At the obvious midpoint the anti-aliased body of every stroke is thrown
		away, and on paper that did not read as "slightly light": the colon in
		an address, a full stop, the dots that tell Arabic letters apart and
		both horizontal rules were simply **absent**.
		"""
		import io as _io

		from PIL import Image

		# 150 is inside the band a font's edge pixels live in — dark enough to
		# be part of the letter, light enough that a midpoint discards it.
		out = _io.BytesIO()
		Image.new("L", (8, 8), 150).save(out, format="PNG")

		rendered = service.png_to_escpos(out.getvalue(), cut=False)
		body = rendered.payload[len(service.INIT) + 8 :]

		self.assertNotEqual(set(body), {0}, "a mid-grey stroke printed as blank paper")

	def test_white_paper_is_still_left_alone(self):
		"""Raising it must not start firing dots at the background."""
		rendered = service.png_to_escpos(_white_png(64, 8), cut=False)
		body = rendered.payload[len(service.INIT) + 8 :]

		self.assertEqual(set(body), {0})

	def test_cutting_is_the_printer_s_setting(self):
		png = _white_png(64, 8)

		self.assertTrue(service.png_to_escpos(png, cut=True).payload.endswith(service.FEED_AND_CUT))
		self.assertFalse(service.png_to_escpos(png, cut=False).payload.endswith(service.FEED_AND_CUT))


class TestTheConnection(FrappeTestCase):
	"""What a printer may be saved with, by connection type.

	Validated without saving: the rules are the controller's, and a saved
	printer would need a branch and an agent that say nothing about them.
	"""

	def _printer(self, **fields):
		return frappe.get_doc(
			{"doctype": "POS Printer", "title": "RPOS Connection Test", "branch": BRANCH, **fields}
		)

	def test_a_windows_printer_is_saved_by_its_name_alone(self):
		"""`D-212` — found by the user: it was refused for want of a USB vendor id."""
		printer = self._printer(
			connection_type="windows",
			windows_printer_name="  EPSON TM-T70 Receipt ",
			ip_address="192.168.8.192",
			usb_vendor_id="04b8",
		)

		printer.validate_connection()

		self.assertEqual(printer.windows_printer_name, "EPSON TM-T70 Receipt")
		self.assertIsNone(printer.ip_address)
		self.assertIsNone(printer.usb_vendor_id)

	def test_a_windows_printer_needs_its_name(self):
		printer = self._printer(connection_type="windows", windows_printer_name="  ")

		with self.assertRaisesRegex(frappe.ValidationError, "Windows Printer Name"):
			printer.validate_connection()

	def test_a_usb_printer_still_needs_its_ids(self):
		printer = self._printer(connection_type="usb", windows_printer_name="EPSON TM-T70 Receipt")

		with self.assertRaisesRegex(frappe.ValidationError, "USB Vendor ID"):
			printer.validate_connection()

	def test_a_print_width_that_is_a_typo_is_refused(self):
		"""`D-215` — 5120 for 512 would draw every receipt ten times too wide."""
		with self.assertRaisesRegex(frappe.ValidationError, "Print Width"):
			self._printer(print_width_dots=5120).validate_print_width()

		self._printer(print_width_dots=512).validate_print_width()
		self._printer(print_width_dots=0).validate_print_width()

	def test_a_network_printer_forgets_a_windows_name(self):
		printer = self._printer(
			connection_type="network", ip_address="192.168.8.192", windows_printer_name="EPSON"
		)

		printer.validate_connection()

		self.assertIsNone(printer.windows_printer_name)


class TestTheRightToLeftMark(FrappeTestCase):
	"""Both halves of the condition, because both were measured (D-090)."""

	def test_arabic_with_digits_is_marked(self):
		"""Unmarked, the renderer draws only the tail of it."""
		self.assertTrue(service.rtl("برغر لحم 200 جرام").startswith(service.RLM))
		self.assertTrue(service.rtl("ضريبة القيمة المضافة 15%").startswith(service.RLM))

	def test_arabic_without_digits_is_left_alone(self):
		"""Marking it is what turned "شيش طاووق" into "ﺱ طاووق"."""
		self.assertEqual(service.rtl("شيش طاووق"), "شيش طاووق")

	def test_the_text_itself_is_never_changed(self):
		"""Only prefixed. A filter that rewrote a dish name would be worse."""
		for text in ("برغر لحم 200 جرام", "شيش طاووق", "Cash", "طاولة 5"):
			self.assertTrue(service.rtl(text).endswith(text))

	def test_nothing_renders_as_the_word_none(self):
		self.assertEqual(service.rtl(None), "")

	def test_it_is_registered_as_a_jinja_filter(self):
		"""The templates call it as `| rtl`; unregistered, every print fails."""
		rendered = frappe.render_template("{{ 'قطعة 200 جرام' | rtl }}", {})
		self.assertTrue(rendered.startswith(service.RLM))


class TestWhichTemplate(FrappeTestCase):
	def test_the_shipped_default_is_found(self):
		name = service.resolve_template("customer_receipt", paper_width="80mm", branch=BRANCH)
		self.assertEqual(frappe.db.get_value("POS Print Template", name, "template_type"), "customer_receipt")

	def test_a_branch_template_beats_the_default(self):
		"""A branch that customised its receipt keeps it."""
		title = "RPOS Test Branch Receipt"
		if not frappe.db.exists("POS Print Template", title):
			frappe.get_doc(
				{
					"doctype": "POS Print Template",
					"title": title,
					"title_ar": "اختبار",
					"template_type": "customer_receipt",
					"paper_width": "80mm",
					"branch": BRANCH,
					"template_html": "<html><body>branch</body></html>",
				}
			).insert(ignore_permissions=True)

		self.assertEqual(
			service.resolve_template("customer_receipt", paper_width="80mm", branch=BRANCH),
			title,
		)

	def test_an_explicit_choice_beats_everything(self):
		self.assertEqual(
			service.resolve_template(
				"customer_receipt", paper_width="80mm", branch=BRANCH, explicit="Customer Receipt 58mm"
			),
			"Customer Receipt 58mm",
		)

	def test_no_template_is_an_error_not_a_blank_page(self):
		"""A missing template must stop, not render an empty roll of paper."""
		with self.assertRaises(frappe.ValidationError):
			service.resolve_template("shift_report", paper_width="nonsense", branch=BRANCH)


class TestAJobIsAddressed(PrintingTestBase):
	def test_a_kot_reaches_its_station_s_printer(self):
		kot = self._sent_kot()
		job = service.print_kot(kot.name)

		self.assertIsNotNone(job)
		doc = frappe.get_doc("POS Print Job", job)
		self.assertEqual(doc.printer, self.printer)
		self.assertEqual(doc.agent, self.agent)
		self.assertEqual(doc.job_type, "kot")
		self.assertEqual(doc.reference_name, kot.name)
		self.assertEqual(doc.status, "queued")
		self.assertGreater(doc.payload_bytes, 0)

	def test_the_agent_is_copied_not_followed(self):
		"""Moving a printer to another agent must not move a queued job.

		A ticket already rendered for the kitchen printer belongs to whoever
		owned it when it was queued; re-reading the link at claim time would let
		an edit on a form redirect work that is already in flight.
		"""
		kot = self._sent_kot()
		job = service.print_kot(kot.name)

		other = _agent("RPOS Test Other Agent")
		frappe.db.set_value("POS Printer", self.printer, "print_agent", other)

		self.assertEqual(frappe.db.get_value("POS Print Job", job, "agent"), self.agent)
		frappe.db.set_value("POS Printer", self.printer, "print_agent", self.agent)

	def test_a_station_with_no_printer_says_so(self):
		"""BR-070 level 7 has run out and `pending` would be a lie."""
		frappe.db.set_value("Production Center", self.grill, "printer", None)
		frappe.db.set_value("POS Profile", self.profile, "default_printer", None)

		kot = self._sent_kot()
		self.assertIsNone(service.print_kot(kot.name))
		self.assertEqual(frappe.db.get_value("Kitchen Order Ticket", kot.name, "print_status"), "failed")

	def test_a_station_that_does_not_auto_print_stays_pending(self):
		"""Nobody asked. Not printed, and not failed either."""
		frappe.db.set_value("Production Center", self.grill, "auto_print_on_send", 0)
		try:
			kot = self._sent_kot()
			self.assertIsNone(service.print_kot(kot.name))
			self.assertEqual(frappe.db.get_value("Kitchen Order Ticket", kot.name, "print_status"), "pending")
		finally:
			frappe.db.set_value("Production Center", self.grill, "auto_print_on_send", 1)

	def test_a_reprint_prints_even_when_the_station_does_not_auto_print(self):
		"""A reprint is a person asking for paper (FR-6.4)."""
		frappe.db.set_value("Production Center", self.grill, "auto_print_on_send", 0)
		try:
			kot = self._sent_kot()
			self.assertIsNotNone(service.print_kot(kot.name, force=True))
		finally:
			frappe.db.set_value("Production Center", self.grill, "auto_print_on_send", 1)

	def test_a_printer_with_no_agent_is_refused(self):
		frappe.db.set_value("POS Printer", self.printer, "print_agent", None)
		try:
			kot = self._sent_kot()
			# print_kot swallows it, which is the contract — but it must not
			# have queued anything for nobody to collect.
			before = frappe.db.count("POS Print Job")
			service.print_kot(kot.name)
			self.assertEqual(frappe.db.count("POS Print Job"), before)
		finally:
			frappe.db.set_value("POS Printer", self.printer, "print_agent", self.agent)


class TestWhatTheKitchenReads(PrintingTestBase):
	"""A cook reads names, not document ids (D-087)."""

	def test_the_station_is_named_not_numbered(self):
		kot = self._sent_kot()
		center = frappe.get_doc("Production Center", kot.production_center)

		context = service.kot_context(kot, center)

		self.assertEqual(context["station"], center.title_ar or center.title)
		self.assertNotEqual(context["station"], kot.production_center)

	def test_the_table_is_its_number_not_its_record(self):
		"""The record's name is long enough to widen the page.

		In an RTL ticket that pushes the start of every line off the right edge
		of the roll, and the item names print sheared off — which is what the
		first real kitchen ticket did.
		"""
		table = frappe.db.get_value("Restaurant Table", {}, ["name", "table_number"], as_dict=True)
		if not table:
			self.skipTest("no tables on this site")

		kot = self._sent_kot()
		kot.db_set("table", table.name, update_modified=False)
		kot.reload()

		context = service.kot_context(kot, frappe.get_doc("Production Center", kot.production_center))

		self.assertEqual(context["table_number"], table.table_number)

	def test_a_ticket_with_no_table_still_renders(self):
		"""Takeaway has no table, and a missing one must not stop the food."""
		kot = self._sent_kot()
		kot.db_set("table", None, update_modified=False)
		kot.reload()

		context = service.kot_context(kot, frappe.get_doc("Production Center", kot.production_center))

		self.assertIsNone(context["table_number"])
		self.assertIsNotNone(service.print_kot(kot.name))


class TestTheAgentSeam(PrintingTestBase):
	def _as_agent(self):
		user = frappe.db.get_value("POS Print Agent", self.agent, "user")
		frappe.set_user(user)
		return user

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def test_claiming_marks_the_job_taken(self):
		kot = self._sent_kot()
		job = service.print_kot(kot.name)
		self._as_agent()

		claimed = api.claim(version="test", host="bench")
		names = [row["name"] for row in claimed]

		self.assertIn(job, names)
		self.assertEqual(frappe.db.get_value("POS Print Job", job, "status"), "claimed")

	def test_a_claim_carries_the_connection_not_the_document(self):
		"""The agent gets an address and bytes, and nothing else about the sale."""
		kot = self._sent_kot()
		service.print_kot(kot.name)
		self._as_agent()

		row = api.claim()[0]

		self.assertEqual(row["printer"]["ip_address"], "127.0.0.1")
		self.assertEqual(row["printer"]["port"], 9100)
		self.assertTrue(base64.b64decode(row["payload"]).startswith(service.INIT))

	def test_a_windows_printer_is_named_to_the_agent_as_windows_lists_it(self):
		"""`D-212` — a USB printer on a Windows PC is reached through its spooler,
		and the name is the whole address."""
		frappe.db.set_value(
			"POS Printer",
			self.printer,
			{"connection_type": "windows", "windows_printer_name": "POS-X Thermal Printer"},
		)
		frappe.clear_document_cache("POS Printer", self.printer)
		kot = self._sent_kot()
		service.print_kot(kot.name)
		self._as_agent()

		row = api.claim()[0]

		self.assertEqual(row["printer"]["connection_type"], "windows")
		self.assertEqual(row["printer"]["windows_printer_name"], "POS-X Thermal Printer")

	def _measured_width(self, dots):
		frappe.db.set_value("POS Printer", self.printer, "print_width_dots", dots)
		frappe.clear_document_cache("POS Printer", self.printer)
		self.addCleanup(frappe.clear_document_cache, "POS Printer", self.printer)
		self.addCleanup(frappe.db.set_value, "POS Printer", self.printer, "print_width_dots", 0)

	def test_a_ticket_is_drawn_as_wide_as_the_printer_reaches_not_as_its_paper(self):
		"""`D-215` — a 180 dpi head on 80mm paper reaches 512 dots; drawn at 576,
		the right of every Arabic line fell off the user's receipt."""
		self._measured_width(512)
		kot = self._sent_kot()

		with patch.object(service, "html_to_png", wraps=service.html_to_png) as render:
			service.print_kot(kot.name)

		self.assertEqual(render.call_args.kwargs["width_dots"], 512)

	def test_the_test_page_ruler_marks_512_for_a_180_dpi_printer(self):
		"""Where somebody finds the number to type in the first place."""
		frappe.db.set_value("POS Printer", self.printer, "paper_width", "80mm")
		frappe.clear_document_cache("POS Printer", self.printer)

		with patch.object(service, "html_to_png", wraps=service.html_to_png) as render:
			api.test_print(self.printer)

		self.assertIn(">512<", render.call_args.args[0])

	def test_a_claimed_job_is_not_handed_out_twice(self):
		"""Two tickets in the kitchen become two plates of food."""
		kot = self._sent_kot()
		service.print_kot(kot.name)
		self._as_agent()

		first = {row["name"] for row in api.claim()}
		second = {row["name"] for row in api.claim()}

		self.assertTrue(first)
		self.assertFalse(first & second)

	def test_a_job_the_agent_never_reported_comes_back(self):
		"""An agent killed mid-print must not strand a ticket forever."""
		kot = self._sent_kot()
		job = service.print_kot(kot.name)
		self._as_agent()
		api.claim()

		frappe.db.set_value(
			"POS Print Job",
			job,
			"claimed_at",
			add_to_date(now_datetime(), seconds=-(api.STALE_CLAIM_SECONDS + 10)),
		)

		self.assertIn(job, [row["name"] for row in api.claim()])
		self.assertEqual(frappe.db.get_value("POS Print Job", job, "attempts"), 1)

	def test_a_ticket_whose_moment_has_passed_is_not_printed(self):
		"""D-108 — a kitchen ticket has a shelf life.

		An agent switched off all day and connected at closing would otherwise
		print every ticket the day queued: a cook receiving twenty orders that
		were served, cancelled or paid hours ago, with no way to tell which.
		"""
		kot = self._sent_kot()
		job = service.print_kot(kot.name)
		frappe.db.set_value(
			"POS Print Job",
			job,
			"creation",
			add_to_date(now_datetime(), minutes=-(api.STALE_AFTER_MINUTES + 1)),
			update_modified=False,
		)

		self._as_agent()
		claimed = [row["name"] for row in api.claim()]

		self.assertNotIn(job, claimed)
		self.assertEqual(frappe.db.get_value("POS Print Job", job, "status"), "failed")

	def test_it_is_marked_rather_than_deleted(self):
		"""'Queued and never printed' is the answer to a real question."""
		kot = self._sent_kot()
		job = service.print_kot(kot.name)
		frappe.db.set_value(
			"POS Print Job",
			job,
			"creation",
			add_to_date(now_datetime(), minutes=-(api.STALE_AFTER_MINUTES + 1)),
			update_modified=False,
		)

		self._as_agent()
		api.claim()

		self.assertTrue(frappe.db.exists("POS Print Job", job))
		self.assertTrue(frappe.db.get_value("POS Print Job", job, "error"))

	def test_an_expired_ticket_says_so_on_the_ticket_too(self):
		"""`D-211` — the job was marked failed while its ticket kept saying
		`pending`, so the order screen could never warn about the one failure
		that lasts longest: a printer off all afternoon."""
		kot = self._sent_kot()
		job = service.print_kot(kot.name)
		frappe.db.set_value(
			"POS Print Job",
			job,
			"creation",
			add_to_date(now_datetime(), minutes=-(api.STALE_AFTER_MINUTES + 1)),
			update_modified=False,
		)

		self._as_agent()
		api.claim()

		self.assertEqual(frappe.db.get_value("Kitchen Order Ticket", kot.name, "print_status"), "failed")
		self.assertFalse(
			frappe.db.exists("POS Print Job", {"retry_of": job}),
			"too late for its printer, too late for the backup",
		)

	def test_a_fresh_ticket_is_untouched_by_that(self):
		kot = self._sent_kot()
		job = service.print_kot(kot.name)

		self._as_agent()

		self.assertIn(job, [row["name"] for row in api.claim()])

	def test_an_agent_cannot_report_on_another_agent_s_job(self):
		kot = self._sent_kot()
		job = service.print_kot(kot.name)

		other = _agent("RPOS Test Other Agent")
		frappe.set_user(frappe.db.get_value("POS Print Agent", other, "user"))

		with self.assertRaises(frappe.PermissionError):
			api.report(job=job, printed=1)

	def test_a_user_who_is_not_an_agent_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			pos_print_agent.for_session()


class TestWhatTheAgentReports(PrintingTestBase):
	def test_a_printed_job_marks_its_ticket_printed(self):
		"""One answer, not two (CLAUDE.md §5.5)."""
		kot = self._sent_kot()
		job = service.print_kot(kot.name)

		service.settle(job, printed=True)

		self.assertEqual(frappe.db.get_value("POS Print Job", job, "status"), "printed")
		self.assertEqual(frappe.db.get_value("Kitchen Order Ticket", kot.name, "print_status"), "printed")
		self.assertEqual(frappe.db.get_value("Kitchen Order Ticket", kot.name, "printer_used"), self.printer)

	def test_a_failure_goes_to_the_fallback_printer(self):
		"""BR-072 — the same bytes, somewhere else."""
		kot = self._sent_kot()
		job = service.print_kot(kot.name)

		service.settle(job, printed=False, error="Connection refused")

		retry = frappe.db.get_value(
			"POS Print Job", {"retry_of": job}, ["name", "printer", "status", "payload"], as_dict=True
		)
		self.assertIsNotNone(retry)
		self.assertEqual(retry.printer, self.backup_printer)
		self.assertEqual(retry.status, "queued")
		self.assertEqual(retry.payload, frappe.db.get_value("POS Print Job", job, "payload"))

	def test_the_fallback_does_not_fall_back_again(self):
		"""One hop. A chain that loops prints until the paper runs out."""
		kot = self._sent_kot()
		job = service.print_kot(kot.name)
		service.settle(job, printed=False, error="first")

		retry = frappe.db.get_value("POS Print Job", {"retry_of": job}, "name")
		service.settle(retry, printed=False, error="second")

		self.assertFalse(frappe.db.exists("POS Print Job", {"retry_of": retry}))

	def test_a_failure_says_what_went_wrong(self):
		# No backup: with one, the ticket is still on its way (`D-211`, below).
		frappe.db.set_value("POS Printer", self.printer, "fallback_printer", None)
		kot = self._sent_kot()
		job = service.print_kot(kot.name)

		service.settle(job, printed=False, error="Out of paper")

		self.assertEqual(frappe.db.get_value("POS Print Job", job, "error"), "Out of paper")
		self.assertEqual(frappe.db.get_value("Kitchen Order Ticket", kot.name, "print_status"), "failed")

	def test_a_ticket_the_backup_may_still_print_is_not_yet_failed(self):
		"""`D-211` — a warning now would send the cashier to reprint a ticket about
		to come out of the backup printer: two tickets, two plates."""
		kot = self._sent_kot()
		job = service.print_kot(kot.name)

		service.settle(job, printed=False, error="Connection refused")

		self.assertEqual(frappe.db.get_value("Kitchen Order Ticket", kot.name, "print_status"), "pending")

	def test_when_the_backup_fails_too_the_ticket_is_failed(self):
		kot = self._sent_kot()
		job = service.print_kot(kot.name)
		service.settle(job, printed=False, error="first")
		retry = frappe.db.get_value("POS Print Job", {"retry_of": job}, "name")

		service.settle(retry, printed=False, error="second")

		self.assertEqual(frappe.db.get_value("Kitchen Order Ticket", kot.name, "print_status"), "failed")


class TheOrderScreenIsToldWhatDidNotPrint(PrintingTestBase):
	"""`D-211` — a printer that is off used to fail in silence: the ticket said
	`failed` on a desk form, and the cook simply got nothing."""

	def test_a_ticket_that_did_not_print_is_named_with_its_station(self):
		frappe.db.set_value("POS Printer", self.printer, "fallback_printer", None)
		kot = self._sent_kot()
		service.settle(service.print_kot(kot.name), printed=False, error="Out of paper")

		state = order_api.get_order(kot.restaurant_order)

		self.assertEqual([row["kot_name"] for row in state["unprinted_tickets"]], [kot.name])
		title, title_ar = frappe.db.get_value("Production Center", self.grill, ["title", "title_ar"])
		self.assertEqual(state["unprinted_tickets"][0]["station"], title)
		self.assertEqual(state["unprinted_tickets"][0]["station_ar"], title_ar or title)
		self.assertEqual(state["tickets_printing"], 0)

	def test_a_ticket_on_its_way_is_counted_not_warned_about(self):
		kot = self._sent_kot()
		service.print_kot(kot.name)

		state = order_api.get_order(kot.restaurant_order)

		self.assertEqual(state["unprinted_tickets"], [])
		self.assertEqual(state["tickets_printing"], 1)

	def test_a_printed_ticket_is_neither(self):
		kot = self._sent_kot()
		service.settle(service.print_kot(kot.name), printed=True)

		state = order_api.get_order(kot.restaurant_order)

		self.assertEqual((state["unprinted_tickets"], state["tickets_printing"]), ([], 0))


class TestTheShippedTemplates(FrappeTestCase):
	"""They are the thing a customer is handed, and they render on the server."""

	def test_every_shipped_template_is_installed(self):
		for template_type in print_templates.SOURCES:
			for paper_width in print_templates.ROOT_PX:
				self.assertTrue(
					frappe.db.exists(
						"POS Print Template",
						{"template_type": template_type, "paper_width": paper_width, "is_default": 1},
					),
					f"{template_type} {paper_width} is missing",
				)

	def test_an_untouched_template_takes_a_correction(self):
		"""A fix to a shipped template must reach sites that already have it.

		The first real receipt printed the currency into the total. Without this,
		the repair would have reached new installations only, and every site that
		migrated before it would have kept the bug for good.
		"""
		title = "Customer Receipt 80mm"
		frappe.db.set_value(
			"POS Print Template", title, "template_html", "<html>stale</html>", update_modified=False
		)

		print_templates.create_default_templates()

		self.assertNotEqual(
			frappe.db.get_value("POS Print Template", title, "template_html"), "<html>stale</html>"
		)

	def test_a_template_somebody_edited_is_never_overwritten(self):
		"""A restaurant's own receipt design is theirs."""
		title = "Bill Preview 80mm"
		mine = "<html><body>my own receipt</body></html>"

		doc = frappe.get_doc("POS Print Template", title)
		doc.template_html = mine
		doc.save(ignore_permissions=True)

		print_templates.create_default_templates()

		self.assertEqual(frappe.db.get_value("POS Print Template", title, "template_html"), mine)


class TestTheCustomerReceipt(PaymentTestBase):
	"""Built on the payment base, because a receipt needs a real invoice.

	A Sales Invoice needs a fiscal year, a warehouse and a default customer that
	only `PaymentTestBase` arranges — and a receipt rendered from a hand-made
	dict would prove nothing about the one a customer is handed.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.agent = _agent("RPOS Test Agent")
		cls.printer = _printer("RPOS Test Printer", agent=cls.agent)
		frappe.db.commit()

	def setUp(self):
		super().setUp()
		frappe.db.set_value("POS Printer", self.printer, "print_agent", self.agent)
		frappe.db.delete("POS Print Job", {"agent": self.agent})

	def test_a_paid_order_queues_a_receipt_on_the_cashier_s_printer(self):
		"""FR-7.5 — it goes with the payment, not with a button."""
		frappe.db.set_value("POS Profile", self.profile, "default_printer", self.printer)
		result = self._pay(self._payable_order())

		# `process_payment` enqueues rather than renders, so this calls what the
		# worker would call — covering the render itself, not the intent to.
		job = service.print_receipt(result["sales_invoice"], order_name=result["order_name"])

		self.assertIsNotNone(job)
		doc = frappe.get_doc("POS Print Job", job)
		self.assertEqual(doc.job_type, "customer_receipt")
		self.assertEqual(doc.printer, self.printer)
		self.assertEqual(doc.reference_name, result["sales_invoice"])
		self.assertGreater(doc.payload_bytes, 0)

	def test_a_terminal_with_no_printer_queues_nothing_and_does_not_raise(self):
		"""The money has already moved; a printer cannot undo that."""
		frappe.db.set_value("POS Profile", self.profile, "default_printer", None)
		result = self._pay(self._payable_order())

		self.assertIsNone(service.print_receipt(result["sales_invoice"], order_name=result["order_name"]))

	def _printed_template(self, receipt_template: str | None) -> str:
		frappe.db.set_value(
			"POS Profile",
			self.profile,
			{"default_printer": self.printer, "receipt_template": receipt_template},
		)
		self.addCleanup(frappe.db.set_value, "POS Profile", self.profile, "receipt_template", None)
		result = self._pay(self._payable_order())

		with patch.object(service, "render_html", wraps=service.render_html) as render:
			job = service.print_receipt(result["sales_invoice"], order_name=result["order_name"])

		self.assertIsNotNone(job)
		return render.call_args.args[0]

	def test_the_template_chosen_on_the_terminal_is_what_prints(self):
		"""D-214 — and sent as it is: a design for other paper is the restaurant's
		to judge on the roll, not something refused here."""
		paper = frappe.db.get_value("POS Printer", self.printer, "paper_width")
		other_paper = frappe.db.get_value(
			"POS Print Template",
			{"template_type": "customer_receipt", "paper_width": ["!=", paper]},
			"name",
		)

		self.assertEqual(self._printed_template(other_paper), other_paper)

	def test_a_terminal_that_chose_nothing_prints_the_resolved_receipt(self):
		paper = frappe.db.get_value("POS Printer", self.printer, "paper_width")

		self.assertEqual(
			self._printed_template(None),
			service.resolve_template("customer_receipt", paper_width=paper, branch=BRANCH),
		)


class TestTheFinancialReportOnPaper(PaymentTestBase):
	"""`D-219` — the X and Z reports, on the terminal's printer.

	Built on the payment base for a real sale in the drawer: a report printed
	over a drawer that took nothing proves the template renders, and nothing
	about the figures a manager reads off it.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.agent = _agent("RPOS Test Agent")
		cls.printer = _printer("RPOS Test Printer", agent=cls.agent)
		frappe.db.commit()

	def setUp(self):
		super().setUp()
		frappe.db.set_value("POS Printer", self.printer, {"print_agent": self.agent, "is_active": 1})
		frappe.db.set_value("POS Profile", self.profile, "default_printer", self.printer)
		frappe.db.delete("POS Print Job", {"agent": self.agent})

	def _till(self) -> str:
		from restaurant_pos.utils import shift as shift_service

		return shift_service.selling_till(self.profile).name

	def _printed(self, entry: str):
		with (
			patch.object(service, "render_html", wraps=service.render_html) as render,
			patch.object(service, "html_to_png", wraps=service.html_to_png) as png,
		):
			job = service.print_shift_report(pos_profile=self.profile, opening_entry=entry)

		self.assertIsNotNone(job)
		self.assertEqual(frappe.db.get_value("POS Print Job", job, "job_type"), "shift_report")
		return render.call_args.args[1], png.call_args.args[0]

	def test_an_open_drawer_prints_an_x_report_of_what_it_took(self):
		self._pay(self._payable_order())

		context, html = self._printed(self._till())

		self.assertEqual(context["kind"], "X")
		self.assertIn(f"{context['report']['sales']:.2f}", html)
		# Nobody has counted a drawer that is still open.
		self.assertIsNone(context["drawers"][0]["counted"])

	def test_a_closed_drawer_prints_z(self):
		"""X or Z is read from the drawer, never passed — a final report over a
		drawer still taking money is not final."""
		entry = self._till()
		frappe.db.set_value("POS Opening Entry", entry, "status", "Closed")
		self.addCleanup(frappe.db.set_value, "POS Opening Entry", entry, "status", "Open")

		context, _ = self._printed(entry)

		self.assertEqual(context["kind"], "Z")

	def test_the_button_is_refused_on_a_terminal_with_no_printer(self):
		"""`D-148` — refused before promising: the paper comes out behind the cashier."""
		from restaurant_pos.api import shift as shift_api

		frappe.db.set_value("POS Profile", self.profile, "default_printer", None)

		with patch.object(service, "enqueue_print") as queued, self.assertRaises(frappe.ValidationError):
			shift_api.print_till_report(self._till())

		queued.assert_not_called()

	def test_the_button_queues_the_drawer_s_report(self):
		from restaurant_pos.api import shift as shift_api

		entry = self._till()
		with patch.object(service, "enqueue_print") as queued:
			shift_api.print_till_report(entry)

		queued.assert_called_once_with("print_shift_report", pos_profile=self.profile, opening_entry=entry)


class TestTheQueueDoesNotGrowForever(PrintingTestBase):
	def test_an_old_finished_job_loses_its_bytes_but_keeps_its_row(self):
		"""D-085 — history is worth keeping; a week-old bitmap is not."""
		kot = self._sent_kot()
		job = service.print_kot(kot.name)
		service.settle(job, printed=True)

		frappe.db.set_value(
			"POS Print Job",
			job,
			"creation",
			add_to_date(now_datetime(), days=-(service.PAYLOAD_DAYS + 1)),
			update_modified=False,
		)

		service.prune_jobs()

		self.assertTrue(frappe.db.exists("POS Print Job", job))
		self.assertFalse(frappe.db.get_value("POS Print Job", job, "payload"))
		self.assertEqual(frappe.db.get_value("POS Print Job", job, "status"), "printed")

	def test_a_job_still_waiting_keeps_its_bytes(self):
		"""Pruning must never empty something that has not printed yet."""
		kot = self._sent_kot()
		job = service.print_kot(kot.name)

		frappe.db.set_value(
			"POS Print Job",
			job,
			"creation",
			add_to_date(now_datetime(), days=-(service.JOB_DAYS + 1)),
			update_modified=False,
		)

		service.prune_jobs()

		self.assertTrue(frappe.db.get_value("POS Print Job", job, "payload"))


class TestTheCashDrawer(PrintingTestBase):
	"""D-093 — the drawer is a printer command, not a device of its own."""

	def setUp(self):
		super().setUp()
		frappe.db.set_value("POS Profile", self.profile, "default_printer", self.printer)

	def test_the_kick_is_five_bytes_of_esc_p(self):
		self.assertEqual(
			service.drawer_kick(2),
			b"\x1bp" + bytes([0, service.DRAWER_ON, service.DRAWER_OFF]),
		)

	def test_pin_five_is_a_different_pulse(self):
		"""A drawer on the wrong pin never opens and says nothing."""
		self.assertNotEqual(service.drawer_kick(2), service.drawer_kick(5))
		self.assertEqual(service.drawer_kick(5)[2], 1)

	def test_opening_it_queues_a_job_for_the_cashier_printer(self):
		job = service.open_drawer(self.profile, reason="test")

		self.assertIsNotNone(job)
		doc = frappe.get_doc("POS Print Job", job)
		self.assertEqual(doc.job_type, "drawer")
		self.assertEqual(doc.printer, self.printer)
		self.assertEqual(base64.b64decode(doc.payload), service.drawer_kick(2))

	def test_the_agent_needs_to_know_nothing_about_drawers(self):
		"""It is bytes on the same queue, claimed like any other job.

		This is the whole reason the drawer needed no agent change: had it been
		a new command the agent had to understand, every restaurant would have
		had to update the program on its machine to get one.
		"""
		service.open_drawer(self.profile, reason="test")
		frappe.set_user(frappe.db.get_value("POS Print Agent", self.agent, "user"))
		try:
			claimed = [row for row in api.claim() if row["job_type"] == "drawer"]
		finally:
			frappe.set_user("Administrator")

		self.assertTrue(claimed)
		self.assertEqual(base64.b64decode(claimed[0]["payload"]), service.drawer_kick(2))

	def test_a_terminal_with_no_printer_does_not_raise(self):
		"""It is called from taking money; it must never stop that."""
		frappe.db.set_value("POS Profile", self.profile, "default_printer", None)

		self.assertIsNone(service.open_drawer(self.profile, reason="test"))


class TestTheTestPage(PrintingTestBase):
	def test_it_queues_a_job_for_the_printer(self):
		result = api.test_print(printer=self.printer)
		doc = frappe.get_doc("POS Print Job", result["job"])

		self.assertEqual(doc.job_type, "test")
		self.assertEqual(doc.printer, self.printer)
		self.assertGreater(doc.payload_bytes, 0)

	def test_it_does_not_depend_on_a_template(self):
		"""It is what tells a printer fault from a template fault.

		If a receipt prints wrong, the test page has to be the fixed thing to
		compare against — so it must not be editable alongside the receipt.
		"""
		self.assertFalse(frappe.db.exists("POS Print Template", {"template_type": "test"}))


class TestAskingForThePaperAgain(ReturnTestBase):
	"""Reprinting a receipt — a sale's, and a refund's (`FR-7.5`, `D-143`).

	The cashier could reprint a *kitchen ticket* and nothing else: the receipt
	the customer actually holds had no way back to paper, for a sale or for a
	return. A till that cannot reprint sends the customer to the office.

	One endpoint answers both, so these tests hold it to the harder half: a
	credit note is on no order — it reverses one — and it still has to find the
	printer it belongs to.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# A reprint now refuses a terminal with no printer (`D-148`), which is the
		# right refusal and makes a printer part of the arrangement here — these
		# tests are about what reaches the queue, not about a shop with no
		# hardware. That case has a test of its own below.
		cls.agent = _agent("RPOS Test Agent")
		cls.printer = _printer("RPOS Test Printer", agent=cls.agent)
		frappe.db.commit()

	def setUp(self):
		super().setUp()
		frappe.db.set_value("POS Profile", self.profile, "default_printer", self.printer)

	def _refund(self, order) -> str:
		result = service_returns.create_return(
			order, items=[{"row": self._row(order), "qty": 1}], reason_code=RETURN_REASON
		)
		return result["credit_note"]

	def test_a_sale_goes_back_on_the_printer(self):
		order = self._paid()

		with patch("restaurant_pos.api.printing.service.enqueue_print") as queued:
			result = api.reprint_receipt(order.sales_invoice)

		queued.assert_called_once_with(
			"print_receipt", invoice_name=order.sales_invoice, order_name=order.name
		)
		self.assertTrue(result["queued"])

	def test_a_refund_finds_the_bill_it_reverses(self):
		"""The credit note is linked to no order; `return_against` is the way home."""
		order = self._paid()
		credit = self._refund(order)

		with patch("restaurant_pos.api.printing.service.enqueue_print") as queued:
			api.reprint_receipt(credit)

		queued.assert_called_once_with("print_receipt", invoice_name=credit, order_name=order.name)

	def test_it_is_audited(self):
		"""08 §5 — paper handed out twice is a thing somebody may have to explain."""
		order = self._paid()
		credit = self._refund(order)

		with patch("restaurant_pos.api.printing.service.enqueue_print"):
			api.reprint_receipt(credit)

		entries = frappe.get_all(
			"POS Audit Log",
			filters={"restaurant_order": order.name, "action_type": "reprint_receipt"},
			fields=["details"],
		)
		details = [frappe.parse_json(row.details) for row in entries]
		self.assertIn({"sales_invoice": credit, "is_return": 1}, details)

	def test_the_same_request_twice_prints_once(self):
		"""09 §8 — a queued reprint replayed after an outage is not two receipts."""
		order = self._paid()

		# A fresh id every run: the sync entry outlives the test that wrote it,
		# so a fixed one would be "already handled" from the second run onwards
		# and this test would pass without ever calling the endpoint.
		queue_id = frappe.generate_hash(length=12)

		with patch("restaurant_pos.api.printing.service.enqueue_print") as queued:
			first = api.reprint_receipt(order.sales_invoice, queue_id=queue_id)
			again = api.reprint_receipt(order.sales_invoice, queue_id=queue_id)

		queued.assert_called_once()
		self.assertEqual(again["invoice"], first["invoice"])
		# The replay says so, rather than pretending to be a fresh print.
		self.assertTrue(again["already_processed"])

	def test_an_invoice_nobody_here_issued_is_refused_by_name(self):
		"""And with a sentence — never a bare framework error (`CLAUDE.md` §5.4)."""
		with self.assertRaises(frappe.ValidationError) as caught:
			api.reprint_receipt("ACC-SINV-NOT-A-THING")

		self.assertIn("ACC-SINV-NOT-A-THING", str(caught.exception))

	def test_a_terminal_with_no_printer_says_so_instead_of_promising(self):
		"""`D-148` — found by pressing the button on a live till.

		The render happens off the request, and `print_receipt` gives up quietly
		when there is no printer — deliberately, because it is also called from
		taking money and a printer must never undo a payment. So the reprint
		endpoint queued a job that produced nothing and the screen said "sent to
		the printer": a confirmation for an event that did not happen, which is
		the one report this product refuses to give (`D-074`).
		"""
		order = self._paid()
		frappe.db.set_value("POS Profile", self.profile, "default_printer", None)

		with patch("restaurant_pos.api.printing.service.enqueue_print") as queued:
			with self.assertRaises(frappe.ValidationError):
				api.reprint_receipt(order.sales_invoice)

		queued.assert_not_called()

	def test_a_cashier_without_the_right_gets_nothing(self):
		order = self._paid()
		frappe.db.set_value("POS Permission Set", "POS Cashier", "can_reprint_receipt", 0)
		cashier = _make_cashier()

		frappe.set_user(cashier)
		frappe.local.rpos_permission_cache = {}
		try:
			with patch("restaurant_pos.api.printing.service.enqueue_print") as queued:
				with self.assertRaises(frappe.PermissionError):
					api.reprint_receipt(order.sales_invoice)

			queued.assert_not_called()
		finally:
			frappe.set_user("Administrator")
			frappe.local.rpos_permission_cache = {}
			frappe.db.set_value("POS Permission Set", "POS Cashier", "can_reprint_receipt", 1)

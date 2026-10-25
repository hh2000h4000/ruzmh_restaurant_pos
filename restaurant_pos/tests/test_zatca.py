# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""ZATCA Phase 1 QR tests.

The payload is not something a person can eyeball on a receipt — it is base64 of
a byte format, and a wrong length byte produces a QR that scans and decodes to
rubbish. So it is decoded back here rather than compared to a string.

Refs: FR-7.5, D-092
"""

import base64
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_datetime

from restaurant_pos.setup.test_fixtures import PROFILE
from restaurant_pos.utils import zatca


def _walk(payload: str) -> dict:
	"""Decode a TLV payload back into {tag: value}, the way a scanner would."""
	raw = base64.b64decode(payload)
	fields = {}
	index = 0
	while index < len(raw):
		tag = raw[index]
		length = raw[index + 1]
		fields[tag] = raw[index + 2 : index + 2 + length].decode("utf-8")
		index += 2 + length
	return fields


class TestTheTagLengthValue(FrappeTestCase):
	def test_a_length_counts_bytes_not_characters(self):
		"""The trap that breaks every Arabic seller and no English one.

		"مطعم" is four characters and eight bytes. A length byte of 4 makes the
		scanner read half the name and then mistake the rest for the next tag —
		the whole payload decodes to rubbish from that point on.
		"""
		encoded = zatca.tlv(zatca.SELLER_NAME, "مطعم")

		self.assertEqual(encoded[0], zatca.SELLER_NAME)
		self.assertEqual(encoded[1], 8)
		self.assertEqual(encoded[2:].decode("utf-8"), "مطعم")

	def test_an_over_long_value_is_cut_on_a_character_boundary(self):
		"""A length byte cannot exceed 255, and half a letter is not UTF-8."""
		encoded = zatca.tlv(zatca.SELLER_NAME, "م" * 200)  # 400 bytes

		self.assertLessEqual(encoded[1], zatca.MAX_VALUE_BYTES)
		# The value must still decode; a truncation mid-character would raise.
		encoded[2:].decode("utf-8")


class TestThePayload(FrappeTestCase):
	def _payload(self, **overrides):
		fields = {
			"seller_name": "مطعم الرُزمة",
			"vat_number": "300000000000003",
			"timestamp": get_datetime("2026-09-01 15:30:00"),
			"invoice_total": 32.0,
			"vat_total": 4.17,
		}
		fields.update(overrides)
		return zatca.qr_payload(**fields)

	def test_it_carries_the_five_fields_in_order(self):
		fields = _walk(self._payload())

		self.assertEqual(sorted(fields), [1, 2, 3, 4, 5])
		self.assertEqual(fields[zatca.SELLER_NAME], "مطعم الرُزمة")
		self.assertEqual(fields[zatca.VAT_NUMBER], "300000000000003")

	def test_amounts_carry_two_decimals(self):
		"""`32` and `32.00` are the same number and not the same field."""
		fields = _walk(self._payload(invoice_total=32, vat_total=4.1))

		self.assertEqual(fields[zatca.INVOICE_TOTAL], "32.00")
		self.assertEqual(fields[zatca.VAT_TOTAL], "4.10")

	def test_the_timestamp_is_utc_and_says_so(self):
		"""Stamped with a Z it has earned, not one assumed.

		A naive Frappe timestamp is in the site's timezone; writing it straight
		out with a Z would put the QR three hours off its own printed time in
		Riyadh.
		"""
		fields = _walk(self._payload())
		stamp = fields[zatca.TIMESTAMP]

		self.assertTrue(stamp.endswith("Z"))
		self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
		self.assertNotIn("15:30:00", stamp)

	def test_it_is_valid_base64(self):
		base64.b64decode(self._payload(), validate=True)


class TestAnInvoiceWithoutAVatNumber(FrappeTestCase):
	def test_no_qr_rather_than_an_invalid_one(self):
		"""Tag 2 *is* the VAT number; a QR without it only looks compliant."""
		company = frappe.db.get_value("Company", {}, "name")
		original = frappe.db.get_value("Company", company, "tax_id")
		frappe.db.set_value("Company", company, "tax_id", None)
		frappe.clear_cache(doctype="Company")

		try:
			invoice = frappe._dict(
				company=company,
				posting_date="2026-09-01",
				posting_time="15:30:00",
				rounded_total=32.0,
				grand_total=32.0,
				total_taxes_and_charges=4.17,
			)
			self.assertIsNone(zatca.invoice_qr(invoice))
		finally:
			frappe.db.set_value("Company", company, "tax_id", original)
			frappe.clear_cache(doctype="Company")


class TestTheIntegrationOwnsTheQr(FrappeTestCase):
	"""`D-154` — whose QR goes on the paper when a ZATCA app is installed.

	Phase one is a specification and both implementations satisfy it. **Phase
	two is not**: its QR carries a cryptographic stamp issued after clearance,
	which nothing here can produce. So the integration is the authority whenever
	it has an answer, and this is the one place that decides — the receipt and
	the printed copy read the same function, and cannot disagree.

	These test the **decision**, not the integration: what it produces is its
	own business, and it is not installed on the suite's site.
	"""

	def _invoice(self):
		return frappe._dict(
			name="ACC-SINV-TEST-0001",
			company="RPOS Test Co",
			posting_date="2026-09-06",
			posting_time="13:00:00",
			rounded_total=32.0,
			grand_total=32.0,
			total_taxes_and_charges=4.17,
		)

	def test_the_integration_wins_when_it_answers(self):
		with patch.object(zatca, "integration_qr", return_value="data:image/png;base64,THEIRS"):
			self.assertEqual(zatca.invoice_qr(self._invoice()), "data:image/png;base64,THEIRS")

	def test_we_answer_when_it_does_not(self):
		"""A site with no integration still prints a compliant phase-one code."""
		company = frappe.db.get_value("POS Profile", PROFILE, "company")
		frappe.db.set_value("Company", company, "tax_id", "300000000000003")
		frappe.clear_document_cache("Company", company)

		invoice = self._invoice()
		invoice.company = company

		with patch.object(zatca, "integration_qr", return_value=None):
			ours = zatca.invoice_qr(invoice)

		self.assertTrue(ours and ours.startswith("data:image/png;base64,"))

	def test_nothing_is_asked_of_an_app_that_is_not_installed(self):
		"""And it never raises — a print must not fail over an integration."""
		self.assertNotIn(zatca.INTEGRATION, frappe.get_installed_apps())
		self.assertIsNone(zatca.integration_qr(self._invoice()))


class TestTheStampedQrIsReadOffTheDocument(FrappeTestCase):
	"""`D-271` — the phase-two lookup failed on every print, logged without why.

	`qr_image_src` is a property of the app's document, not a column, and the
	log carried «RPOS zatca» where the traceback belonged. The app is not
	installed on the suite's site, so its record is stood in for.
	"""

	invoice = frappe._dict(name="ACC-SINV-TEST-0002")

	def test_an_invoice_the_app_never_processed_has_no_stamped_qr(self):
		with (
			patch.object(frappe.db, "get_value", return_value=None),
			patch.object(frappe, "get_doc") as get_doc,
		):
			self.assertIsNone(zatca._stamped_qr(self.invoice))
		get_doc.assert_not_called()

	def test_the_qr_comes_from_the_document_s_own_property(self):
		record = frappe._dict(qr_image_src="data:image/png;base64,STAMPED")
		with (
			patch.object(frappe.db, "get_value", return_value="SIAF-0001"),
			patch.object(frappe, "get_doc", return_value=record),
		):
			self.assertEqual(zatca._stamped_qr(self.invoice), "data:image/png;base64,STAMPED")

	def test_a_failure_is_logged_with_its_traceback(self):
		def broken():
			raise ValueError("the reason")

		with patch.object(frappe, "log_error") as logged:
			self.assertIsNone(zatca._tried("phase two", broken))

		logged.assert_called_once_with(title="ZATCA integration failed at phase two")

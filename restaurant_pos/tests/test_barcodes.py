# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Drawing a QR (`D-250`).

Moved here with the drawing itself, out of the ZATCA tests: the same helper puts
a tax code on a receipt and a coupon code on a card, and only one of those is
about tax.

Refs: FR-7.4, D-092, D-250
"""

import base64
import io

from frappe.tests.utils import FrappeTestCase

from restaurant_pos.utils import barcodes


class TestTheImage(FrappeTestCase):
	def test_it_is_a_png_of_whole_modules(self):
		"""Fractional modules print grey on thermal paper and misread."""
		png = barcodes.qr_png("RPOSTEST")

		self.assertTrue(png.startswith(b"\x89PNG"))

		from PIL import Image

		image = Image.open(io.BytesIO(png))
		self.assertEqual(image.size[0], image.size[1])
		self.assertEqual(image.size[0] % barcodes.MODULE_SCALE, 0)

	def test_a_longer_payload_draws_a_bigger_code(self):
		"""The matrix grows with what is in it — nothing is being cropped."""
		small = barcodes.qr_png("A")
		large = barcodes.qr_png("A" * 200)

		from PIL import Image

		self.assertLess(
			Image.open(io.BytesIO(small)).size[0],
			Image.open(io.BytesIO(large)).size[0],
		)

	def test_the_data_uri_is_what_an_img_tag_wants(self):
		uri = barcodes.qr_data_uri("test")

		self.assertTrue(uri.startswith("data:image/png;base64,"))
		base64.b64decode(uri.split(",", 1)[1], validate=True)

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Drawing a QR — the part that has nothing to do with what is inside it.

Lived in `utils/zatca` because the tax QR was the first thing that needed one,
and a coupon card needs the same drawing with a different payload (`D-250`). A
module named after a Saudi tax rule is the wrong place to import from to put a
code on a voucher, so the drawing moved here and `zatca` keeps only the part
that is about tax.

Refs: FR-7.4, D-092, D-250
"""

from __future__ import annotations

import base64
import io

#: Dots per QR module. Four keeps the code about 200 dots across on 80mm paper —
#: large enough for a phone camera, small enough to leave room for the total.
MODULE_SCALE = 4

#: Modules of blank margin. The specification for QR codes calls for four, and a
#: code printed without it is one a scanner may refuse at an angle.
QUIET_ZONE = 4


def qr_png(payload: str, *, scale: int = MODULE_SCALE, quiet: int = QUIET_ZONE) -> bytes:
	"""Draw the QR as a bitmap at exact module size.

	Drawn from the module matrix rather than asked for as a scaled image: a
	receipt prints at 203 dpi in one-bit black, and a QR resampled to a
	fractional module size prints with grey edges that scanners misread. Whole
	dots per module is the whole point.
	"""
	import pyqrcode
	from PIL import Image

	# `M` recovers from about 15% damage — the right trade for thermal paper,
	# which smudges and fades, against a payload this small.
	matrix = pyqrcode.create(payload, error="M").code

	modules = len(matrix)
	side = (modules + quiet * 2) * scale
	image = Image.new("1", (side, side), 1)
	pixels = image.load()

	for row, line in enumerate(matrix):
		for column, module in enumerate(line):
			if not module:
				continue
			for y in range((row + quiet) * scale, (row + quiet + 1) * scale):
				for x in range((column + quiet) * scale, (column + quiet + 1) * scale):
					pixels[x, y] = 0

	out = io.BytesIO()
	image.save(out, format="PNG")
	return out.getvalue()


def qr_data_uri(payload: str, **kwargs) -> str:
	"""The QR as a `data:` URI, so the template needs no file and no server."""
	encoded = base64.b64encode(qr_png(payload, **kwargs)).decode("ascii")
	return f"data:image/png;base64,{encoded}"

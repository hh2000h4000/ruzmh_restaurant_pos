# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The till's sale document is named in one place, and stays named there (`D-311`).

`utils/sale_doc.py` exists so that turning the till's sale into a `POS Invoice`
(`D-308`) is one line and not seventy. That only holds while nobody writes the
name out again — and the place it gets written out again is the next report,
by somebody who has never opened that file. A report reading the old table
after the switch shows an empty day and raises nothing.

So this reads the source, the way `test_api_surface.py` does: a property of the
whole app, checked once, rather than a habit to remember.
"""

import ast
import pathlib
import unittest

from restaurant_pos.utils import sale_doc

PACKAGE = pathlib.Path(__file__).resolve().parent.parent

#: Where the words are spelled out, and why each one may.
SPELLED_OUT = {
	"utils/sale_doc.py": "the one place that names it",
	"restaurant_pos/report/vat_return/vat_return.py": (
		"the return's sales side is the till's sales and the office's own Sales Invoices, each named"
	),
	"restaurant_pos/report/actual_vs_theoretical_usage/actual_vs_theoretical_usage.py": (
		"stock ledger voucher types: whatever took the stock, by whichever document"
	),
}

#: Both spellings: what the till's sale was, and what it is now (`D-308`). Code
#: that writes either one has stopped asking `sale_doc` what a sale is.
NAMES = {"Sales Invoice", "Sales Invoice Item", "POS Invoice", "POS Invoice Item"}


def _spelled_out_in(path: pathlib.Path) -> list[int]:
	tree = ast.parse(path.read_text(encoding="utf-8"))
	return sorted(
		node.lineno
		for node in ast.walk(tree)
		if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in NAMES
	)


class TheSaleDocumentIsNamedOnce(unittest.TestCase):
	"""Reads the source, so it needs no site."""

	def test_no_code_spells_the_sale_document_out(self):
		found = {}
		for path in sorted(PACKAGE.rglob("*.py")):
			relative = path.relative_to(PACKAGE).as_posix()
			if relative.startswith("tests/") or relative in SPELLED_OUT:
				continue
			lines = _spelled_out_in(path)
			if lines:
				found[relative] = lines

		self.assertEqual(
			found,
			{},
			"These spell the till's sale document out. Read it from `utils/sale_doc.py` "
			"(`SALE`, `SALE_ITEM`) — or, if the code means a Sales Invoice whatever the till "
			"sells as, add the file to SPELLED_OUT in this test with the reason.",
		)

	def test_every_exemption_still_spells_it_out_and_says_why(self):
		"""A stale exemption reads as a decision that still applies to something."""
		for relative, why in SPELLED_OUT.items():
			self.assertTrue((why or "").strip(), relative)
			self.assertTrue(_spelled_out_in(PACKAGE / relative), f"{relative} no longer spells it out")

	def test_a_line_of_the_sale_belongs_to_the_sale(self):
		self.assertEqual(sale_doc.SALE_ITEM, f"{sale_doc.SALE} Item")

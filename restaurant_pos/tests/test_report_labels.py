# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Every column in our reports reads in Arabic, and in our words (`D-283`).

The owner found them one at a time: «جدول» over the tables (`D-280`), then
«كمية» over an amount. Both were ERPNext's own Arabic for a common English
word — right in its screens, wrong in ours — and a sweep found «النتائج» over
the bill a refund reverses, «اللقب» over an offer's name, and two headings with
no Arabic at all. So the report labels are scoped to `RPOS report`, and this
reads every one of them the way the owner's screen does.

Refs: D-174, D-280, D-283
"""

import glob
import os
import re

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.translate import get_all_translations

#: Whitespace-tolerant: `ruff format` wraps a long label over several lines, and a
#: pattern that read one line only would skip exactly those, silently.
LABEL = re.compile(r'"label":\s*_\(\s*"([^"]+)"(?:,\s*context="([^"]+)")?\s*,?\s*\)')

#: ERPNext's Arabic for these words means something else in a restaurant report.
WRONG = {"كمية", "النتائج", "اللقب", "السلعة", "أمين الصندوق", "جدول"}


def _labels() -> list[tuple[str, str | None, str]]:
	root = frappe.get_app_path("restaurant_pos", "restaurant_pos", "report")
	found = []
	for path in glob.glob(os.path.join(root, "*", "*.py")):
		report = os.path.basename(os.path.dirname(path))
		for match in LABEL.finditer(open(path, encoding="utf-8").read()):
			found.append((match.group(1), match.group(2), report))
	return found


class EveryColumnReadsInArabic(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.arabic = get_all_translations("ar")

	def _arabic(self, label: str, context: str | None) -> str | None:
		return (context and self.arabic.get(f"{label}:{context}")) or self.arabic.get(label)

	def test_no_column_is_left_in_english(self):
		missing = sorted(
			{f"{report}: {label}" for label, context, report in _labels() if not self._arabic(label, context)}
		)
		self.assertEqual(missing, [], "columns with no Arabic")

	def test_no_column_borrows_a_word_that_means_something_else(self):
		wrong = sorted(
			{
				f"{report}: {label} → {self._arabic(label, context)}"
				for label, context, report in _labels()
				if self._arabic(label, context) in WRONG
			}
		)
		self.assertEqual(wrong, [], "columns reading as ERPNext's word for something else")

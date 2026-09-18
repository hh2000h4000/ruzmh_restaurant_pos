# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Every `frappe.call` on a desk form reaches a real, whitelisted method.

**Written because one did not.** The POS Profile's pairing button called
``restaurant_pos.restaurant_pos.api.session.issue_device_code`` — the path our
DocType controllers use, with the module folder in it — and `api` does not sit
there. The manager pressed the button and read *No module named*, which is a
sentence no restaurant owner should have to act on, and no test we had would
have caught it: the endpoint existed, the tests called it directly, and only the
string in the browser was wrong.
"""

import ast
import importlib
import re
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

#: `method: "some.dotted.path"` in a `frappe.call`, in either quote.
CALL = re.compile(r"""method:\s*["']([\w.]+)["']""")

APP = Path(frappe.get_app_path("restaurant_pos"))


def _scripts() -> list[Path]:
	"""Our own desk JavaScript — form scripts and whatever `hooks.py` includes."""
	return sorted(set(APP.glob("public/js/**/*.js")) | set(APP.glob("restaurant_pos/doctype/**/*.js")))


class TestDeskScripts(FrappeTestCase):
	def test_every_button_calls_something_that_exists(self):
		for script in _scripts():
			for path in CALL.findall(script.read_text(encoding="utf-8")):
				with self.subTest(script=script.name, method=path):
					module_path, _, attribute = path.rpartition(".")
					try:
						module = importlib.import_module(module_path)
					except ModuleNotFoundError as error:
						self.fail(f"{script.name}: {path} — {error}")

					self.assertTrue(
						hasattr(module, attribute),
						f"{script.name}: {module_path} has no {attribute}",
					)

	def test_every_button_calls_something_whitelisted(self):
		"""A method Frappe will not serve is refused at the browser, not here."""
		for script in _scripts():
			for path in CALL.findall(script.read_text(encoding="utf-8")):
				with self.subTest(script=script.name, method=path):
					module_path, _, attribute = path.rpartition(".")
					method = getattr(importlib.import_module(module_path), attribute)
					self.assertIn(
						method,
						frappe.whitelisted,
						f"{script.name}: {path} is not whitelisted",
					)

	def test_the_scripts_parse(self):
		"""A syntax error in a form script is silent: the buttons simply never appear."""
		for script in _scripts():
			with self.subTest(script=script.name):
				body = script.read_text(encoding="utf-8")
				self.assertEqual(body.count("{"), body.count("}"), "unbalanced braces")
				self.assertEqual(body.count("("), body.count(")"), "unbalanced brackets")


class TestThisTestSeesTheProject(FrappeTestCase):
	def test_it_found_the_scripts_at_all(self):
		"""A glob that matches nothing passes every assertion above it."""
		names = {script.name for script in _scripts()}

		self.assertIn("pos_profile.js", names)
		self.assertIn("pos_print_agent.js", names)

	def test_the_pattern_finds_calls(self):
		self.assertEqual(CALL.findall('method: "a.b.c",'), ["a.b.c"])
		self.assertIsInstance(ast.parse("x = 1"), ast.Module)

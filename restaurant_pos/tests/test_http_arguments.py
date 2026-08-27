# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Whitelisted endpoints must accept what a browser actually sends.

A browser sends a list or an object as a **JSON string**. Frappe checks an
argument against its annotation *before* the function body runs
(`frappe/utils/typing_validations.py`), so a parameter annotated `list` is
refused with a 417 and a message the client never sees — the endpoint's own
`parse_json` never gets the chance to run.

Every other test calls these functions from Python with real lists, which is
why the suite stayed green while the order screen was refusing every item. This
one checks the shape the wire actually carries.

Refs: 07 §3, 06_git_testing_rules.md
"""

import inspect
import types
import typing

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant_pos.api import order, payment, permissions, session

MODULES = (order, payment, permissions, session)

#: The annotations a browser can only satisfy with a JSON string. Numbers are
#: not here: Frappe coerces "3" to an int on its own.
STRUCTURED = (list, dict)


def _members(annotation) -> tuple:
	origin = typing.get_origin(annotation)
	if origin in (typing.Union, types.UnionType):
		return typing.get_args(annotation)
	return (annotation,)


def _is_structured(annotation) -> bool:
	return any(member in STRUCTURED for member in _members(annotation))


def _accepts_str(annotation) -> bool:
	return str in _members(annotation)


class TestWhitelistedArgumentTypes(FrappeTestCase):
	def test_every_structured_argument_also_accepts_a_json_string(self):
		offenders = []

		for module in MODULES:
			for name, function in vars(module).items():
				if not callable(function) or not getattr(function, "__wrapped__", function).__module__:
					continue
				if not getattr(function, "whitelisted", False) and not hasattr(function, "__wrapped__"):
					continue

				target = getattr(function, "__wrapped__", function)
				if target.__module__ != module.__name__:
					continue

				for parameter in inspect.signature(target).parameters.values():
					annotation = parameter.annotation
					if annotation is inspect.Parameter.empty:
						continue

					if _is_structured(annotation) and not _accepts_str(annotation):
						offenders.append(f"{module.__name__}.{name}({parameter.name}: {annotation})")

		self.assertEqual(
			offenders,
			[],
			"these arguments cannot be sent from a browser: a JSON string is refused with a 417",
		)

	def test_a_json_string_survives_the_validator_and_is_parsed(self):
		"""Through the guard the HTTP handler applies, which a direct call skips.

		Calling a whitelisted function from Python bypasses
		`validate_argument_types` entirely — which is why the whole suite stayed
		green while every browser request was refused with a 417. Applying it
		here is what makes this test reproduce the wire.
		"""
		from frappe.utils.typing_validations import validate_argument_types

		group = frappe.db.get_value("POS Modifier Group", {}, "name")
		if not group:
			self.skipTest("no modifier group on this site")

		guarded = validate_argument_types(session.get_modifier_groups)
		rows = guarded(groups=frappe.as_json([group]))

		self.assertEqual([row["name"] for row in rows], [group])

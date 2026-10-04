# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Every whitelisted endpoint is authorised, or is listed here saying why not.

`CLAUDE.md` §4.2 asks each `@frappe.whitelist()` to check login, then branch,
then the permission set. The checks themselves are well placed — `_load` does it
once for the whole order family, `assert_mutable` carries the shift gate for
every mutation (`D-058`) — but **nothing failed if an endpoint skipped them**.
The suite tests the guards; it never tested that they are reached. An endpoint
added next month that forgets `_load` passes all 437 of the others.

So this walks the app's own call graph from each endpoint and looks for a guard.
It is the same idea as `test_http_arguments.py`: check a property of the whole
API surface rather than one endpoint at a time, because the endpoint nobody
thought to test is exactly the one that is wrong.

An endpoint with no branch to check is not a failure — a customer is not owned
by a branch, and a session endpoint acts on the caller's own session. Those go
in `UNSCOPED` **with a reason**, and writing that reason is the point: it makes
skipping the check a decision somebody made rather than one nobody noticed.

Refs: CLAUDE.md §4.2, D-058, FR-8 (08_Security.md)
"""

import ast
import pathlib
import unittest

#: Reaching any of these means the caller has been authorised.
#:
#: `assert_mutable` is here because it is a gate in its own right (`D-058`): it
#: refuses when no shift is open on the terminal, and everything that changes an
#: order goes through it.
#:
#: **`validate_branch_access` counted here while it asked only the branch
#: question** — and a single-branch restaurant restricts nobody, so this file
#: passed an API open to every signed-in account (`D-208`). It now calls
#: `assert_pos_user` first, which is also a guard on its own for the endpoints
#: that name no branch. `has_permission` is the desk forms' guard: an endpoint
#: serving a form follows that form's own DocType permission.
GUARDS = frozenset(
	{
		"validate_branch_access",
		"assert_pos_user",
		"assert_permission",
		"assert_mutable",
		"require_manager",
		"has_permission",
	}
)

#: How deep to follow calls. The API layer is thin on purpose — parse,
#: authorise, delegate (`02_backend_rules.md`) — so a guard is one or two hops
#: away. A limit keeps a cycle from hanging the suite.
MAX_DEPTH = 6

#: Endpoints that check no branch, and why each one does not need to.
#:
#: Being on this list is not an exemption from authentication: Frappe refuses a
#: whitelisted call from Guest unless the endpoint says `allow_guest`, and only
#: one does. It means there is no *branch* to scope the call to.
UNSCOPED = {
	# The caller has no session yet, or is acting on the session they have.
	"api.auth.sign_in": (
		"no session yet — wrong PINs lock the device (D-204), a till role is required (D-208), "
		"and every failure is audited without the PIN"
	),
	"api.auth.sign_out": "ends the caller's own session",
	"api.auth.me": "reports the caller's own session",
	"api.auth.clock_in": "the caller's own attendance",
	"api.auth.clock_out": "the caller's own attendance",
	"api.session.csrf_token": "issues a token for the caller's own session",
	"api.session.ping": "answers whether the server is reachable",
	"api.session.pair_device": (
		"a one-time code from a manager is the authorisation, and it names the terminal itself; "
		"guesses are locked out per device like the PIN pad (D-204, D-226)"
	),
	# `customer.*` and `session.get_modifier_groups` stood here as "not
	# branch-scoped" — true, and it left every customer's phone number readable
	# by any signed-in account. They name no branch, so they call
	# `assert_pos_user` themselves and need no exemption (`D-208`).
	# The print agent authenticates with its own key pair, and is answered only
	# about the jobs belonging to that agent.
	"api.printing.claim": "authenticated by the agent's api key; scoped to that agent's own jobs",
	"api.printing.report": "authenticated by the agent's api key; scoped to that agent's own jobs",
	# Desk-only, on the DocType itself, behind ERPNext's own document
	# permissions rather than the POS permission set.
	"api.session.issue_device_code": (
		"desk action on the POS Profile, behind ERPNext document permissions (D-226)"
	),
	"api.quick_setup.run": ("desk page, inserting as the caller behind ERPNext document permissions (D-307)"),
	"api.session.unpair_device": (
		"desk action on the POS Profile, behind ERPNext document permissions (D-226)"
	),
	# Read from the till's bell and from the desk form alike, by office staff
	# with no till role; it writes only the caller's own recipient rows.
	"api.bell.mark_announcements_read": "touches only the signed-in person's own recipient rows (D-303)",
	"restaurant_pos.doctype.pos_print_agent.pos_print_agent.generate_keys": (
		"desk action on the DocType, behind ERPNext document permissions"
	),
	"restaurant_pos.doctype.pos_print_agent.pos_print_agent.issue_pairing_code": (
		"desk action on the DocType, behind ERPNext document permissions (D-212)"
	),
	"restaurant_pos.doctype.pos_print_agent.pos_print_agent.pair": (
		"a machine with no credentials yet exchanges a one-time, ten-minute code for its "
		"agent's keys; guesses are locked out per device like the PIN pad (D-204, D-212)"
	),
}

#: The only endpoints a signed-out caller may use. **Each one is a conversation**:
#: the PIN pad, because a locked till has nobody signed in; the print agent's
#: pairing, because a machine being installed has no key yet (`D-212`); and the
#: till's own pairing, because the PIN pad belongs to a terminal, so the terminal
#: must be known before anybody can sign in at all (`D-226`). All three are
#: authorised by something the caller has to have been given — a PIN or a
#: one-time code — and all three are locked out per device on repeated failures.
GUEST_ENDPOINTS = {
	"api.auth.sign_in",
	"api.session.pair_device",
	"restaurant_pos.doctype.pos_print_agent.pos_print_agent.pair",
}

PACKAGE = pathlib.Path(__file__).resolve().parent.parent


def _dotted(path: pathlib.Path) -> str:
	"""`…/utils/shift.py` -> `utils.shift`, the way an import names it."""
	return ".".join(path.relative_to(PACKAGE).with_suffix("").parts)


def _is_whitelisted(node: ast.FunctionDef) -> tuple[bool, bool]:
	"""(whitelisted, allows guests)."""
	for decorator in node.decorator_list:
		call = decorator if isinstance(decorator, ast.Call) else None
		name = getattr(call.func if call else decorator, "attr", None)
		if name != "whitelist":
			continue
		guest = any(
			keyword.arg == "allow_guest" and getattr(keyword.value, "value", False)
			for keyword in (call.keywords if call else [])
		)
		return True, guest
	return False, False


class Module:
	"""One source file: the functions it defines and the modules it imports."""

	def __init__(self, path: pathlib.Path):
		self.dotted = _dotted(path)
		tree = ast.parse(path.read_text(encoding="utf-8"))

		self.functions = {
			node.name: node
			for node in ast.walk(tree)
			if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
		}

		# `from restaurant_pos.utils import shift as service` binds `service` to
		# a module; that is how the API layer reaches the code that guards.
		self.aliases: dict[str, str] = {}
		for node in ast.walk(tree):
			if not isinstance(node, ast.ImportFrom) or not (node.module or "").startswith("restaurant_pos"):
				continue
			base = node.module[len("restaurant_pos.") :] if node.module != "restaurant_pos" else ""
			for alias in node.names:
				target = f"{base}.{alias.name}" if base else alias.name
				self.aliases[alias.asname or alias.name] = target


def _load_app() -> dict[str, Module]:
	modules = {}
	for path in sorted(PACKAGE.rglob("*.py")):
		if "tests" in path.relative_to(PACKAGE).parts:
			continue
		module = Module(path)
		modules[module.dotted] = module
	return modules


class TheApiSurfaceIsAuthorised(unittest.TestCase):
	"""Reads the source, so it needs no site and no fixtures."""

	@classmethod
	def setUpClass(cls):
		cls.modules = _load_app()
		cls.endpoints = {
			f"{module.dotted}.{name}": (module, node)
			for module in cls.modules.values()
			for name, node in module.functions.items()
			if _is_whitelisted(node)[0]
		}

	# ------------------------------------------------------------------ #

	def _reaches_guard(self, module: Module, node: ast.AST, depth: int, seen: set) -> bool:
		"""Does a guard lie anywhere within `depth` calls of here?"""
		if depth <= 0:
			return False

		for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
			target, where = call.func, module

			if isinstance(target, ast.Name):
				name = target.id
			elif isinstance(target, ast.Attribute):
				name = target.attr
				# `service.open_till` — follow the alias to the module it names.
				holder = getattr(target.value, "id", None)
				if holder and holder in module.aliases:
					where = self.modules.get(module.aliases[holder], module)
			else:
				continue

			if name in GUARDS:
				return True

			# A guard may also be reached through a helper, which is how this
			# app is meant to work: `_load` checks the branch once for the whole
			# order family rather than twenty endpoints each remembering to.
			key = f"{where.dotted}.{name}"
			if key in seen:
				continue
			seen.add(key)

			nested = where.functions.get(name)
			if nested is not None and self._reaches_guard(where, nested, depth - 1, seen):
				return True

		return False

	# ------------------------------------------------------------------ #

	def test_every_endpoint_is_authorised_or_says_why_not(self):
		"""The whole point: a new endpoint cannot quietly skip the check."""
		unguarded = sorted(
			key
			for key, (module, node) in self.endpoints.items()
			if key not in UNSCOPED and not self._reaches_guard(module, node, MAX_DEPTH, set())
		)

		self.assertEqual(
			unguarded,
			[],
			"These endpoints reach no branch or permission check.\n"
			"Either call one — `_load` for an order, `validate_branch_access` "
			"otherwise — or add the endpoint to UNSCOPED in this file with the "
			"reason it needs none:\n  " + "\n  ".join(unguarded),
		)

	def test_the_unscoped_list_names_endpoints_that_exist(self):
		"""A stale exemption is worse than none: it reads as a decision that
		still applies to something."""
		gone = sorted(key for key in UNSCOPED if key not in self.endpoints)
		self.assertEqual(gone, [], f"UNSCOPED names endpoints that no longer exist: {gone}")

	def test_every_unscoped_endpoint_gives_a_reason(self):
		blank = sorted(key for key, why in UNSCOPED.items() if not (why or "").strip())
		self.assertEqual(blank, [], f"UNSCOPED entries with no reason: {blank}")

	def test_only_signing_in_is_open_to_guests(self):
		"""`allow_guest` hands the endpoint to anyone who can reach the server.

		One endpoint needs it — a locked terminal has no session, so the person
		about to sign in is a guest. Any second one is worth a conversation.
		"""
		guests = {key for key, (_, node) in self.endpoints.items() if _is_whitelisted(node)[1]}
		self.assertEqual(
			guests,
			GUEST_ENDPOINTS,
			"An endpoint gained or lost `allow_guest=True`. Anything reachable "
			"without signing in must be deliberate.",
		)

	def test_the_walk_found_the_endpoints_at_all(self):
		"""Guards against the quiet failure of this whole file: if the parse or
		the path resolution breaks, every other test above passes on an empty
		set and reports nothing wrong."""
		self.assertGreater(len(self.endpoints), 50, "Too few endpoints found — the source walk is broken")
		guarded = [
			key
			for key, (module, node) in self.endpoints.items()
			if self._reaches_guard(module, node, MAX_DEPTH, set())
		]
		self.assertGreater(len(guarded), 25, "No endpoint resolved to a guard — alias resolution is broken")

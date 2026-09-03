# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The print agent's own tests, run by the app's suite.

`print_agent/` is a sibling of the app, not part of it — a single file copied to
a machine inside the restaurant and started as a service. That is also how it
fell outside every gate: `ruff check restaurant_pos` never saw it, and
`bench run-tests --app restaurant_pos` never ran its tests. **The one component
that runs unattended, all night, next to the printers was the one component
nothing checked.**

Its tests need no site and no fixtures, so there is no reason for them to be a
separate command somebody has to remember. This runs them where the rest of the
suite runs, and fails here when they fail.

Refs: D-084, D-112
"""

import io
import pathlib
import sys
import unittest

#: `…/restaurant_pos/restaurant_pos/tests/this.py` -> the repo root beside the
#: app. `resolve()` matters: the app is a symlink into the working copy
#: (`D-011`), and the agent lives next to the real files, not next to the link.
AGENT = pathlib.Path(__file__).resolve().parents[3] / "print_agent"


class ThePrintAgentsOwnTests(unittest.TestCase):
	def test_they_pass(self):
		"""Runs the agent's suite in-process and reports its failures as ours."""
		if not (AGENT / "test_rpos_print_agent.py").exists():
			# Installed by `bench get-app` from a package that did not carry the
			# agent. Skipping is right; failing would tell a site that its app
			# is broken because a file it does not need is missing.
			self.skipTest(f"no print agent beside the app at {AGENT}")

		sys.path.insert(0, str(AGENT))
		try:
			suite = unittest.TestLoader().discover(str(AGENT), pattern="test_*.py")
			# Its output is swallowed; what matters here is the verdict, and any
			# failure is re-raised below with the case that caused it.
			result = unittest.TextTestRunner(verbosity=0, stream=io.StringIO()).run(suite)
		finally:
			sys.path.remove(str(AGENT))
			for name in [m for m in sys.modules if m.startswith(("rpos_print_agent", "test_rpos"))]:
				del sys.modules[name]

		self.assertTrue(
			result.wasSuccessful(),
			"The print agent's tests failed:\n"
			+ "\n".join(f"  {case}: {why.splitlines()[-1]}" for case, why in result.failures + result.errors),
		)
		self.assertGreater(result.testsRun, 0, f"Found no agent tests in {AGENT}")

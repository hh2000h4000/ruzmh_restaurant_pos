"""Which branch a terminal belongs to — the behaviour as it stands (`D-391`).

The baseline for separating a terminal from its hall. Today a terminal reaches
its branch through `restaurant_section`, and ten places in the code work that
out. These tests say what each of them answers, in terms that do not name the
route: when the terminal is given a branch of its own, every one of them must
still pass, unchanged. A test here that has to be edited to pass afterwards is a
behaviour that changed.

Refs: D-040, D-226, D-309, D-354, D-391
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant_pos.api import auth as auth_api
from restaurant_pos.api import session as session_api
from restaurant_pos.setup.test_fixtures import BRANCH, PROFILE
from restaurant_pos.utils import order as orders
from restaurant_pos.utils import printing, quick_setup, shift
from restaurant_pos.utils.invoice_number import DEVICE_NUMBER, series_for

OTHER_BRANCH = "RPOS Baseline Branch"


def _hall(branch: str, title: str, *, kind: str = "dine_in") -> str:
	"""A hall. Its tables follow its kind: a counter has none, set on save."""
	existing = frappe.db.get_value("Restaurant Section", {"title": title, "branch": branch}, "name")
	if existing:
		return existing
	return (
		frappe.get_doc(
			{
				"doctype": "Restaurant Section",
				"title": title,
				"title_ar": title,
				"branch": branch,
				"section_type": kind,
				"is_active": 1,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _terminal(
	name: str, section: str | None, *, warehouse: str | None = "branch", branch: str | None = None
) -> str:
	"""A terminal like the suite's own, on whatever hall it is given."""
	if frappe.db.exists("POS Profile", name):
		frappe.delete_doc("POS Profile", name, force=True, ignore_permissions=True)

	company = frappe.db.get_value("POS Profile", PROFILE, "company")
	basics = quick_setup.company_basics(company)
	return (
		frappe.get_doc(
			{
				"doctype": "POS Profile",
				"name": name,
				"company": company,
				"currency": frappe.db.get_value("Company", company, "default_currency"),
				"warehouse": basics.warehouse if warehouse == "branch" else warehouse,
				"write_off_account": basics.write_off,
				"write_off_cost_center": basics.cost_center,
				"write_off_limit": 1,
				"customer": quick_setup.walk_in_customer(),
				"restaurant_section": section,
				"rpos_branch": branch,
				"taxes_and_charges": frappe.db.get_value("POS Profile", PROFILE, "taxes_and_charges"),
				"payments": [{"mode_of_payment": quick_setup.cash_method(company), "default": 1}],
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _outsider(name: str, hall: str) -> str:
	"""An ERPNext POS Profile from before the app — no branch, no hall.

	One cannot be saved like that any more (`D-400`), but a site may hold rows
	made before the app was installed. Made the only way one exists now: saved
	whole, then blanked underneath, as the old row would read.
	"""
	from restaurant_pos.utils import terminal_branch

	made = _terminal(name, hall)
	frappe.db.set_value(
		"POS Profile",
		made,
		{"restaurant_section": None, terminal_branch.FIELD: None, DEVICE_NUMBER: None},
		update_modified=False,
	)
	return made


class TerminalBranchTestBase(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		company = frappe.db.get_value("POS Profile", PROFILE, "company")
		if not frappe.db.exists("Branch", OTHER_BRANCH):
			basics = quick_setup.company_basics(company)
			frappe.get_doc(
				{
					"doctype": "Branch",
					"branch": OTHER_BRANCH,
					"company": company,
					"default_warehouse": basics.warehouse,
					"default_cost_center": basics.cost_center,
				}
			).insert(ignore_permissions=True)

		cls.hall = frappe.db.get_value("POS Profile", PROFILE, "restaurant_section")
		cls.terrace = _hall(BRANCH, "RPOS Baseline Terrace")
		cls.counter = _hall(BRANCH, "RPOS Baseline Counter", kind="counter")
		cls.other_hall = _hall(OTHER_BRANCH, "RPOS Baseline Other Hall")

		cls.second = _terminal("RPOS Baseline Second Till", cls.hall)
		cls.elsewhere = _terminal("RPOS Baseline Other Till", cls.other_hall)
		cls.outsider = _outsider("RPOS Baseline Not A Till", cls.hall)


class TestEveryPlaceAgrees(TerminalBranchTestBase):
	"""The ten places that work a terminal's branch out answer alike."""

	def test_the_suites_terminal_is_in_its_branch_everywhere(self):
		self.assertEqual(orders.branch_of_profile(PROFILE), BRANCH)
		self.assertEqual(printing._branch_of_profile(PROFILE), BRANCH)
		self.assertEqual(auth_api._branch_of(PROFILE), BRANCH)
		self.assertEqual(shift._profile(PROFILE).branch, BRANCH)
		self.assertEqual(session_api._profile(PROFILE).branch, BRANCH)

	def test_a_terminal_of_another_branch_is_in_that_branch_everywhere(self):
		self.assertEqual(orders.branch_of_profile(self.elsewhere), OTHER_BRANCH)
		self.assertEqual(printing._branch_of_profile(self.elsewhere), OTHER_BRANCH)
		self.assertEqual(auth_api._branch_of(self.elsewhere), OTHER_BRANCH)
		self.assertEqual(shift._profile(self.elsewhere).branch, OTHER_BRANCH)
		self.assertEqual(session_api._profile(self.elsewhere).branch, OTHER_BRANCH)


class TestTerminalsOfABranch(TerminalBranchTestBase):
	def test_two_terminals_share_one_hall(self):
		"""A hall is not a terminal's own: five tills in one hall are five rows on it."""
		self.assertEqual(orders.branch_of_profile(self.second), BRANCH)
		self.assertIn(PROFILE, orders.profiles_in(BRANCH))
		self.assertIn(self.second, orders.profiles_in(BRANCH))

	def test_terminals_of_one_branch_are_numbered_apart(self):
		"""`D-309` — each has its own number inside the branch."""
		first = frappe.db.get_value("POS Profile", PROFILE, DEVICE_NUMBER)
		second = frappe.db.get_value("POS Profile", self.second, DEVICE_NUMBER)
		self.assertTrue(first and second)
		self.assertNotEqual(first, second)

	def test_branches_do_not_mix(self):
		self.assertNotIn(self.elsewhere, orders.profiles_in(BRANCH))
		self.assertEqual(orders.profiles_in(OTHER_BRANCH), [self.elsewhere])


class TestAProfileOutsideTheTill(TerminalBranchTestBase):
	"""An ERPNext POS Profile nobody made a till of is left as ERPNext's."""

	def test_it_has_no_branch(self):
		self.assertIsNone(orders.branch_of_profile(self.outsider))

	def test_it_is_not_numbered_and_has_no_invoice_series(self):
		self.assertFalse(frappe.db.get_value("POS Profile", self.outsider, DEVICE_NUMBER))
		self.assertIsNone(series_for(self.outsider, number_now=False))

	def test_it_is_not_counted_in_any_branch(self):
		self.assertNotIn(self.outsider, orders.profiles_in(BRANCH))
		self.assertNotIn(self.outsider, orders.profiles_in(OTHER_BRANCH))


class TestTheBranchWarehouse(TerminalBranchTestBase):
	def test_a_terminal_with_no_warehouse_sells_from_its_branchs(self):
		name = _terminal("RPOS Baseline No Warehouse", self.hall, warehouse=None)
		self.assertEqual(
			frappe.db.get_value("POS Profile", name, "warehouse"),
			frappe.db.get_value("Branch", BRANCH, "default_warehouse"),
		)


class TestHallsAndTables(TerminalBranchTestBase):
	def test_the_till_lists_every_hall_of_its_branch_that_has_tables(self):
		"""Every terminal sees all its branch's halls — not only its own."""
		listed = {row["name"] for row in session_api._sections(BRANCH)}
		self.assertIn(self.hall, listed)
		self.assertIn(self.terrace, listed)
		self.assertNotIn(self.counter, listed)
		self.assertNotIn(self.other_hall, listed)

	def test_an_order_with_no_table_is_in_the_terminals_hall(self):
		"""`D-040` — the table decides; the terminal's hall is the fallback."""
		profile = frappe._dict(restaurant_section=self.hall)
		self.assertEqual(orders.section_of_table(None, profile), self.hall)

	def test_an_order_at_a_table_is_in_the_tables_hall(self):
		table = frappe.get_doc(
			{
				"doctype": "Restaurant Table",
				"table_number": "B1",
				"section": self.terrace,
				"capacity": 2,
				"status": "available",
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		profile = frappe._dict(restaurant_section=self.hall)
		self.assertEqual(orders.section_of_table(table.name, profile), self.terrace)


class TestTheBranchColumn(TerminalBranchTestBase):
	"""Stage 2 (`D-391`): `rpos_branch` is filled from the hall and never disagrees."""

	def test_every_terminal_says_what_its_hall_says(self):
		from restaurant_pos.utils import terminal_branch

		terminal_branch.fill_from_halls()
		self.assertEqual(terminal_branch.mismatches(), [])
		for name in (PROFILE, self.second, self.elsewhere):
			self.assertEqual(
				frappe.db.get_value("POS Profile", name, terminal_branch.FIELD),
				orders.branch_of_profile(name),
			)

	def test_a_profile_with_no_hall_gets_no_branch(self):
		from restaurant_pos.utils import terminal_branch

		terminal_branch.fill_from_halls()
		self.assertFalse(frappe.db.get_value("POS Profile", self.outsider, terminal_branch.FIELD))

	def test_a_new_terminal_takes_its_halls_branch(self):
		from restaurant_pos.utils import terminal_branch

		name = _terminal("RPOS Baseline Fresh Till", self.other_hall)
		self.assertEqual(frappe.db.get_value("POS Profile", name, terminal_branch.FIELD), OTHER_BRANCH)

	def test_a_hall_of_another_branch_is_refused(self):
		doc = frappe.get_doc("POS Profile", self.second)
		doc.restaurant_section = self.other_hall
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_the_fill_stops_on_a_terminal_that_disagrees(self):
		from restaurant_pos.utils import terminal_branch

		frappe.db.set_value(
			"POS Profile", self.second, terminal_branch.FIELD, OTHER_BRANCH, update_modified=False
		)
		with self.assertRaises(frappe.ValidationError) as caught:
			terminal_branch.fill_from_halls()
		self.assertIn(self.second, str(caught.exception))
		frappe.db.set_value("POS Profile", self.second, terminal_branch.FIELD, BRANCH, update_modified=False)


class TestOneSource(TerminalBranchTestBase):
	"""Stage 3 (`D-393`): every place asks `terminal_branch.branch_of`."""

	def test_a_terminal_with_a_branch_and_no_hall_is_a_till(self):
		"""The column alone makes a till — numbered, counted, and in its branch."""
		from restaurant_pos.utils import terminal_branch

		name = _terminal("RPOS Baseline Hall-less Till", None, branch=OTHER_BRANCH)

		self.assertEqual(terminal_branch.branch_of(name), OTHER_BRANCH)
		self.assertEqual(orders.branch_of_profile(name), OTHER_BRANCH)
		self.assertTrue(terminal_branch.is_till(name))
		self.assertIn(name, orders.profiles_in(OTHER_BRANCH))
		self.assertTrue(frappe.db.get_value("POS Profile", name, DEVICE_NUMBER))
		self.assertEqual(shift._profile(name).branch, OTHER_BRANCH)

	def test_an_empty_column_falls_back_to_the_hall(self):
		"""Transitional: a site whose migrate has not filled the column yet."""
		from restaurant_pos.utils import terminal_branch

		frappe.db.set_value("POS Profile", self.second, terminal_branch.FIELD, None, update_modified=False)
		self.assertEqual(terminal_branch.branch_of(self.second), BRANCH)
		self.assertIn(self.second, orders.profiles_in(BRANCH))
		frappe.db.set_value("POS Profile", self.second, terminal_branch.FIELD, BRANCH, update_modified=False)


class TestDuplicatingATerminal(TerminalBranchTestBase):
	"""What the desk's Duplicate makes of a till (`D-393`).

	Copied the way the button copies — `ignore_no_copy=False`, which drops
	`no_copy` fields as `frappe.model.copy_doc` does in the browser. The default
	`frappe.copy_doc` keeps them, so a test built on it would carry fields the
	button drops. The branch is not one of them (`D-395`): the copy keeps it.
	"""

	def _duplicate(self, source: str, name: str, *, keep_hall: bool = True, keep_branch: bool = True):
		from restaurant_pos.utils import terminal_branch

		copy = frappe.copy_doc(frappe.get_doc("POS Profile", source), ignore_no_copy=False)
		copy.name = None
		copy.set("__newname", name)
		copy.set(DEVICE_NUMBER, None)
		if not keep_hall:
			copy.restaurant_section = None
		if not keep_branch:
			copy.set(terminal_branch.FIELD, None)
		return copy.insert(ignore_permissions=True)

	def test_a_copy_with_its_hall_stays_in_the_branch(self):
		from restaurant_pos.utils import terminal_branch

		copy = self._duplicate(self.elsewhere, "RPOS Baseline Copied Till")
		self.assertEqual(copy.get(terminal_branch.FIELD), OTHER_BRANCH)
		self.assertTrue(terminal_branch.is_till(copy.name))
		self.assertTrue(copy.get(DEVICE_NUMBER))

	def test_a_copy_of_a_till_with_no_hall_stays_in_the_branch(self):
		"""A counter till's copy is a counter till of the same branch (`D-395`)."""
		from restaurant_pos.utils import terminal_branch

		copy = self._duplicate(self.elsewhere, "RPOS Baseline Copied Counter", keep_hall=False)
		self.assertFalse(copy.restaurant_section)
		self.assertEqual(copy.get(terminal_branch.FIELD), OTHER_BRANCH)
		self.assertTrue(terminal_branch.is_till(copy.name))
		self.assertTrue(copy.get(DEVICE_NUMBER))

	def test_a_copy_with_no_hall_and_no_branch_is_refused(self):
		"""`D-400` — a device saves with a branch or not at all."""
		with self.assertRaises(frappe.MandatoryError):
			self._duplicate(self.elsewhere, "RPOS Baseline Copied Plain", keep_hall=False, keep_branch=False)

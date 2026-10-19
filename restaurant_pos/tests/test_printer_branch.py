# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""One branch's paper never reaches another branch's printer (`D-363`).

The load test sent a branch's kitchen tickets to another branch's kitchen
(`D-361`). These hold the other doors shut: a link to another branch's printer
is refused when it is saved, and a job is refused when it is queued.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant_pos.tests.test_order import BRANCH
from restaurant_pos.utils import printing
from restaurant_pos.utils.printing import Rendered

OTHER = "RPOS Test Printer Branch"


def _other_branch() -> str:
	if not frappe.db.exists("Branch", OTHER):
		other = frappe.copy_doc(frappe.get_doc("Branch", BRANCH))
		other.branch = OTHER
		other.rpos_branch_number = None
		other.insert(ignore_permissions=True)
	return OTHER


def _printer(title: str, branch: str):
	return frappe.get_doc(
		{
			"doctype": "POS Printer",
			"title": title,
			"branch": branch,
			"connection_type": "network",
			"ip_address": "127.0.0.1",
			"port": 9100,
			"printer_model": "epson",
			"paper_width": "80mm",
			"print_mode": "image",
			"is_active": 1,
		}
	)


def _kept(title: str, branch: str) -> str:
	"""The class rolls back once, at its end: a printer one test made is there for the next."""
	return frappe.db.get_value("POS Printer", {"title": title, "branch": branch}) or (
		_printer(title, branch).insert(ignore_permissions=True).name
	)


class APrinterBelongsToOneBranch(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.theirs = _kept("RPOS Their Grill", _other_branch())
		self.ours = _kept("RPOS Our Grill", BRANCH)

	def test_a_station_cannot_print_on_another_branchs_printer(self):
		station = frappe.get_doc(
			{
				"doctype": "Production Center",
				"title": "RPOS Crossed Station",
				"title_ar": "RPOS Crossed Station",
				"branch": BRANCH,
				"printer": self.theirs,
			}
		)
		with self.assertRaises(frappe.ValidationError):
			station.insert(ignore_permissions=True)

	def test_a_rule_cannot_send_to_another_branchs_station(self):
		station = frappe.get_doc(
			{
				"doctype": "Production Center",
				"title": "RPOS Their Station",
				"title_ar": "RPOS Their Station",
				"branch": OTHER,
				"printer": self.theirs,
			}
		).insert(ignore_permissions=True)
		rule = frappe.get_doc(
			{
				"doctype": "POS Printer Routing Rule",
				"branch": BRANCH,
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
				"production_center": station.name,
				"priority": 1,
				"is_active": 1,
			}
		)
		with self.assertRaises(frappe.ValidationError):
			rule.insert(ignore_permissions=True)

	def test_a_terminal_cannot_take_another_branchs_printer(self):
		profile = frappe.get_doc(
			"POS Profile",
			frappe.db.get_value("POS Profile", {"restaurant_section": ("is", "set")}, "name"),
		)
		if frappe.db.get_value("Restaurant Section", profile.restaurant_section, "branch") != BRANCH:
			self.skipTest("the test terminal is not in the test branch")
		profile.default_printer = self.theirs
		with self.assertRaises(frappe.ValidationError):
			profile.save(ignore_permissions=True)

	def test_a_fallback_stays_in_the_branch(self):
		mine = frappe.get_doc("POS Printer", self.ours)
		mine.fallback_printer = self.theirs
		with self.assertRaises(frappe.ValidationError):
			mine.save(ignore_permissions=True)

	def test_one_name_once_per_branch_and_again_in_another(self):
		with self.assertRaises(frappe.ValidationError):
			_printer("RPOS Our Grill", BRANCH).insert(ignore_permissions=True)
		# The other branch may have its own «RPOS Our Grill».
		self.assertTrue(_kept("RPOS Our Grill", OTHER))

	def test_a_job_is_refused_on_another_branchs_printer_whatever_chose_it(self):
		with self.assertRaises(frappe.ValidationError):
			printing.queue(
				printer=self.theirs,
				branch=BRANCH,
				job_type="test",
				rendered=Rendered(payload=b"x", width_dots=0, height_dots=0),
			)

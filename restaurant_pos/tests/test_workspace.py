# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The desk pages the app ships.

A workspace is a JSON file that nothing compiles and nothing type-checks: a link
to a DocType that was renamed simply **disappears from the page**, a card whose
`link_count` is wrong silently swallows the links after it, and a shortcut named
in the layout but absent from the record draws nothing at all. Every one of
those is invisible until somebody opens the page and does not miss what was
never there.

Refs: 06_UI_UX_Flow.md, D-150
"""

import json
import pathlib

import frappe
from frappe.tests.utils import FrappeTestCase

WORKSPACES = pathlib.Path(__file__).resolve().parent.parent / "restaurant_pos" / "workspace"


def _pages() -> list[tuple[str, dict]]:
	return [(path.stem, json.loads(path.read_text(encoding="utf-8"))) for path in WORKSPACES.glob("*/*.json")]


class TestTheDeskPages(FrappeTestCase):
	def test_there_are_pages_to_check(self):
		"""The glob is the whole test; an empty one would pass everything."""
		self.assertTrue(_pages())

	def test_every_link_points_at_something_that_exists(self):
		for name, page in _pages():
			for row in page["links"]:
				if row["type"] != "Link":
					continue

				# A report is linked by name as well, and looked up among reports.
				kind = row.get("link_type") or "DocType"
				with self.subTest(page=name, link=row["link_to"]):
					self.assertTrue(
						frappe.db.exists(kind, row["link_to"]),
						f"{name}: link to {row['link_to']}, which is not a {kind}",
					)

	def test_a_script_report_is_linked_as_one(self):
		"""Without `is_query_report` the link opens the report builder on its DocType (`D-196`)."""
		for name, page in _pages():
			for row in page["links"]:
				if row["type"] != "Link" or row.get("link_type") != "Report":
					continue

				with self.subTest(page=name, link=row["link_to"]):
					kind = frappe.db.get_value("Report", row["link_to"], "report_type")
					self.assertEqual(row["is_query_report"], int(kind in ("Script Report", "Query Report")))

	def test_no_link_points_at_a_child_table(self):
		"""A child table has no list view — the link opens an error page."""
		for name, page in _pages():
			for row in page["links"]:
				if row["type"] != "Link":
					continue

				with self.subTest(page=name, link=row["link_to"]):
					self.assertFalse(
						frappe.db.get_value("DocType", row["link_to"], "istable"),
						f"{name}: {row['link_to']} is a child table",
					)

	def test_every_card_says_how_many_links_follow_it(self):
		"""`link_count` slices the list; a wrong number hides the rest."""
		for name, page in _pages():
			counted: dict[str, int] = {}
			declared: dict[str, int] = {}
			current = None

			for row in page["links"]:
				if row["type"] == "Card Break":
					current = row["label"]
					declared[current] = row["link_count"]
					counted[current] = 0
				else:
					counted[current] += 1

			for card, count in counted.items():
				with self.subTest(page=name, card=card):
					self.assertEqual(declared[card], count, f"{name}: card {card!r}")

	def test_the_layout_and_the_record_name_the_same_things(self):
		"""`content` is drawn from; the rest of the record is what it draws."""
		for name, page in _pages():
			blocks = json.loads(page["content"])

			cards = {b["data"]["card_name"] for b in blocks if b["type"] == "card"}
			breaks = {row["label"] for row in page["links"] if row["type"] == "Card Break"}
			self.assertEqual(cards, breaks, f"{name}: cards on the page vs cards in the record")

			shortcuts = {b["data"]["shortcut_name"] for b in blocks if b["type"] == "shortcut"}
			held = {row["label"] for row in page["shortcuts"]}
			self.assertEqual(shortcuts, held, f"{name}: shortcuts on the page vs shortcuts in the record")

	def test_a_child_page_names_a_parent_that_exists(self):
		"""`Printing` hangs under `Restaurant POS`; a typo orphans it silently."""
		labels = {page["name"] for _, page in _pages()}

		for name, page in _pages():
			parent = page.get("parent_page")
			if parent:
				with self.subTest(page=name):
					self.assertIn(parent, labels, f"{name}: parent {parent!r} is not one of ours")

	def test_the_page_the_installer_lands_on_carries_the_till(self):
		"""`FR-11` — the one link nobody should have to be told (`D-150`).

		Everything else on the page is a DocType a manager could reach from the
		awesome bar. The till cannot: it is not a desk page, and an administrator
		who has just installed the app has no way to guess `/restaurant-pos`.
		"""
		page = dict(_pages())["restaurant_pos"]
		urls = [row.get("url") for row in page["shortcuts"] if row["type"] == "URL"]

		self.assertIn("/restaurant-pos", urls)

	def test_every_card_on_the_home_page_opens_a_page_of_ours(self):
		"""`D-346` — the home page is cards now, and a card is only a URL.

		Nothing checks a URL: rename a page and its card opens "not found", on the
		first screen a customer sees after installing.
		"""
		routes = {page["name"].lower().replace(" ", "-") for _, page in _pages()}
		home = dict(_pages())["restaurant_pos"]

		for row in home["shortcuts"]:
			if row["type"] != "URL" or not row["url"].startswith("/app/"):
				continue

			with self.subTest(card=row["label"]):
				self.assertIn(row["url"].removeprefix("/app/"), routes)

	def test_the_home_page_carries_no_list_of_links(self):
		"""`D-346` — forty-five links on one page is what the cards replaced."""
		self.assertEqual(dict(_pages())["restaurant_pos"]["links"], [])

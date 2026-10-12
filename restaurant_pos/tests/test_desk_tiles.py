# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""A desk page as tiles: turning one on, and giving a tile its own look (`D-351`)."""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant_pos.api import desk
from restaurant_pos.setup.desk_tiles import BLOCK

PAGE = "RPOS Tiles Trial"


def _blocks() -> list[dict]:
	return json.loads(frappe.db.get_value("Workspace", PAGE, "content"))


def _drawn() -> dict:
	return desk.tiles(json.dumps({"name": PAGE, "title": PAGE, "public": 1}))


def _clear() -> None:
	"""Saving a workspace commits, so the rollback a test case ends with is not enough."""
	frappe.delete_doc("Workspace", PAGE, force=True, ignore_missing=True)
	settings = frappe.get_doc(desk.SETTINGS)
	settings.tile_colour, settings.tile_size = None, "Medium"
	settings.set("looks", [row for row in settings.looks if row.page != PAGE])
	settings.save()


class TestADeskPageAsTiles(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		_clear()
		frappe.get_doc(
			{
				"doctype": "Workspace",
				"label": PAGE,
				"title": PAGE,
				"public": 1,
				"content": json.dumps(
					[
						{"type": "header", "data": {"text": "A heading", "col": 12}},
						{"type": "shortcut", "data": {"shortcut_name": "Trial orders", "col": 3}},
						{"type": "card", "data": {"card_name": "Staff", "col": 4}},
					]
				),
				"shortcuts": [{"label": "Trial orders", "type": "DocType", "link_to": "Restaurant Order"}],
				"links": [
					{"type": "Card Break", "label": "Staff", "link_count": 1},
					{
						"type": "Link",
						"label": "Trial link",
						"link_type": "DocType",
						"link_to": "Restaurant Order",
					},
				],
			}
		).insert()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.lang = "en"
		_clear()

	def test_the_block_goes_above_the_widgets_and_below_the_heading(self):
		desk.tile_page(PAGE, 1)

		self.assertEqual(
			[block["type"] for block in _blocks()], ["header", "custom_block", "shortcut", "card"]
		)
		self.assertTrue(desk.is_tiled(PAGE))
		self.assertEqual(
			frappe.db.count("Workspace Custom Block", {"parent": PAGE, "custom_block_name": BLOCK}), 1
		)

	def test_turning_it_on_twice_leaves_one_block(self):
		desk.tile_page(PAGE, 1)
		desk.tile_page(PAGE, 1)

		self.assertEqual([block["type"] for block in _blocks()].count("custom_block"), 1)
		self.assertEqual(frappe.db.count("Workspace Custom Block", {"parent": PAGE}), 1)

	def test_turning_it_off_leaves_the_page_as_it_was(self):
		before = _blocks()
		desk.tile_page(PAGE, 1)
		desk.tile_page(PAGE, 0)

		self.assertEqual(_blocks(), before)
		self.assertFalse(desk.is_tiled(PAGE))
		# The widgets were never touched: a page that loses rows here loses them for good.
		self.assertEqual(frappe.db.count("Workspace Shortcut", {"parent": PAGE}), 1)
		self.assertEqual(frappe.db.count("Workspace Link", {"parent": PAGE}), 2)

	def test_a_look_reaches_the_tile_it_was_chosen_for(self):
		desk.style_tile(PAGE, "Card", "Staff", icon="users", colour="#AA3322")
		desk.style_tile(PAGE, "Link", "Trial link", icon="star")
		desk.style_tile(PAGE, "Shortcut", "Trial orders", colour="#112233")

		drawn = _drawn()
		card = drawn["cards"]["items"][0]
		self.assertEqual(card["look"], {"icon": "users", "colour": "#AA3322"})
		self.assertEqual(card["links"][0]["look"]["icon"], "star")
		self.assertEqual(drawn["shortcuts"]["items"][0]["look"]["colour"], "#112233")

	def test_a_look_chosen_in_arabic_is_kept_under_the_rows_own_label(self):
		"""The page shows «الموظفين»; the row says `Staff`, and that is what survives a language change."""
		frappe.local.lang = "ar"
		shown = frappe._("Staff")
		self.assertNotEqual(shown, "Staff")

		desk.style_tile(PAGE, "Card", shown, icon="users")

		kept = frappe.get_doc(desk.SETTINGS).looks
		self.assertEqual([(row.kind, row.label) for row in kept if row.page == PAGE], [("Card", "Staff")])
		self.assertEqual(_drawn()["cards"]["items"][0]["look"]["icon"], "users")

	def test_choosing_again_replaces_and_choosing_nothing_removes(self):
		desk.style_tile(PAGE, "Card", "Staff", icon="users")
		desk.style_tile(PAGE, "Card", "Staff", icon="star")
		self.assertEqual(_drawn()["cards"]["items"][0]["look"]["icon"], "star")

		desk.style_tile(PAGE, "Card", "Staff")
		self.assertNotIn("look", _drawn()["cards"]["items"][0])
		self.assertFalse([row for row in frappe.get_doc(desk.SETTINGS).looks if row.page == PAGE])

	def test_the_sites_colour_and_size_come_with_the_page(self):
		settings = frappe.get_doc(desk.SETTINGS)
		settings.tile_colour, settings.tile_size = "#224466", "Large"
		settings.save()

		drawn = _drawn()
		self.assertEqual(drawn["look"], {"colour": "#224466", "size": "Large"})
		self.assertTrue(drawn["can_style"])

	def test_what_is_not_a_picture_or_a_colour_is_refused(self):
		for wrong in ({"icon": "<svg onload=x>"}, {"colour": "red; background:url(x)"}):
			with self.assertRaises(frappe.ValidationError):
				desk.style_tile(PAGE, "Card", "Staff", **wrong)
		with self.assertRaises(frappe.ValidationError):
			desk.style_tile(PAGE, "Chart", "Staff", icon="users")

	def test_only_whoever_may_edit_the_page_may_dress_it(self):
		frappe.set_user("Guest")

		with self.assertRaises(frappe.PermissionError):
			desk.style_tile(PAGE, "Card", "Staff", icon="users")
		with self.assertRaises(frappe.PermissionError):
			desk.tile_page(PAGE, 1)

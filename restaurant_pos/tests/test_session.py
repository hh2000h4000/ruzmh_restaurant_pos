# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""POS session payload tests.

Refs: 07 §2, 09 §3, FR-1.3, FR-3.5, FR-15.4, 04 §8
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant_pos.api import session
from restaurant_pos.tests.test_order import ITEM, OrderTestBase

#: Items these tests invent. They are sellable, so anything left behind turns up
#: on the cashier's menu — the suite and the demo share one site.
SCRATCH_ITEMS = ["RPOS-TEST-UNPRICED"] + [f"RPOS-TEST-BULK-{index}" for index in range(10)]


class TestLoadPosSession(OrderTestBase):
	def setUp(self):
		frappe.local.rpos_permission_cache = {}

	@classmethod
	def tearDownClass(cls):
		"""Take the scratch items off the menu again.

		A test that adds ten items to prove the catalogue does not go O(n) has
		to remove them, or the next person to open the till sees ten dishes
		called RPOS-TEST-BULK-3.
		"""
		for code in SCRATCH_ITEMS:
			if frappe.db.exists("Item", code):
				for price in frappe.get_all("Item Price", filters={"item_code": code}, pluck="name"):
					frappe.delete_doc("Item Price", price, force=True, ignore_permissions=True)
				frappe.delete_doc("Item", code, force=True, ignore_permissions=True)

		frappe.db.commit()
		super().tearDownClass()

	def _load(self):
		return session.load_pos_session(self.profile)

	def test_the_payload_has_every_key_the_contract_promises(self):
		"""07 §2 — the Vue app is written against exactly these keys."""
		payload = self._load()

		for key in (
			"pos_profile",
			"restaurant_section",
			"screen_layout",
			"order_types",
			"payment_methods",
			"active_shift",
			"items",
			"item_groups",
			"promotions",
			"permissions",
		):
			self.assertIn(key, payload)

	def test_permissions_never_include_a_credential(self):
		payload = self._load()
		self.assertNotIn("manager_pin", payload["permissions"])
		self.assertNotIn("pos_manager_pin", payload["permissions"])

	def test_the_catalog_carries_prices_and_arabic_names(self):
		payload = self._load()
		burger = next(row for row in payload["items"] if row["item_code"] == ITEM)

		self.assertEqual(burger["rate"], 25)
		self.assertTrue(burger["display_name"])
		self.assertIn("modifier_groups", burger)

	def test_an_item_group_brings_its_picture(self):
		"""`D-192` — ERPNext's own `Item Group.image` is the group's tile picture."""
		group = frappe.db.get_value("Item", ITEM, "item_group")
		frappe.db.set_value("Item Group", group, "image", "/files/rpos-test-group.png")

		row = next(row for row in self._load()["item_groups"] if row["name"] == group)

		self.assertEqual(row["image"], "/files/rpos-test-group.png")

	def test_an_item_with_no_price_is_null_not_zero(self):
		"""D-020 — the UI must tell 'unpriced' apart from 'free'."""
		code = "RPOS-TEST-UNPRICED"
		if not frappe.db.exists("Item", code):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": code,
					"item_name": code,
					"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
					"stock_uom": "Nos",
					"is_stock_item": 0,
				}
			).insert(ignore_permissions=True)

		payload = self._load()
		row = next(r for r in payload["items"] if r["item_code"] == code)
		self.assertIsNone(row["rate"])

	def test_order_types_are_the_ones_an_order_could_actually_use(self):
		"""FR-1.3 — the buttons and the create-order guard must agree."""
		from restaurant_pos.utils.order import is_order_type_allowed

		payload = self._load()
		profile = payload["pos_profile"]

		for row in payload["order_types"]:
			config = frappe.get_cached_doc("Restaurant Order Type", row["name"])
			self.assertTrue(
				is_order_type_allowed(config, profile),
				f"{row['name']} was offered but would be refused",
			)

	def test_an_inactive_order_type_is_not_offered(self):
		frappe.db.set_value("Restaurant Order Type", self.dine_in, "is_active", 0)
		frappe.clear_cache(doctype="Restaurant Order Type")
		try:
			offered = {row["name"] for row in self._load()["order_types"]}
			self.assertNotIn(self.dine_in, offered)
		finally:
			frappe.db.set_value("Restaurant Order Type", self.dine_in, "is_active", 1)
			frappe.clear_cache(doctype="Restaurant Order Type")

	def test_an_order_type_restricted_to_another_branch_is_hidden(self):
		"""BR-003."""
		other = frappe.get_doc(
			{
				"doctype": "Restaurant Order Type",
				"title": "RPOS Test Elsewhere",
				"title_ar": "مكان آخر",
				"customer_mode": "optional",
				"send_to_kitchen_on": "manual",
				"is_active": 1,
				"allowed_branches": [{"branch": "_RPOS Nonexistent"}],
			}
		)
		other.flags.ignore_links = True
		other.insert(ignore_permissions=True, ignore_links=True)
		try:
			offered = {row["name"] for row in self._load()["order_types"]}
			self.assertNotIn(other.name, offered)
		finally:
			frappe.delete_doc("Restaurant Order Type", other.name, force=True, ignore_permissions=True)

	def test_a_restriction_pointing_at_nothing_does_not_blank_the_terminal(self):
		"""Debris in allowed_order_types must not leave a till with no buttons.

		A force-deleted order type leaves the link behind. Counting it as a live
		restriction hides every order type and gives the manager nothing to go
		on — the worst failure a till can have.
		"""
		profile = frappe.get_doc("POS Profile", self.profile)
		original = list(profile.allowed_order_types)

		profile.allowed_order_types = []
		profile.append("allowed_order_types", {"order_type": "OT-DOES-NOT-EXIST"})
		# `ignore_links` is a flag, not a save() argument — and it is what lets
		# the test create the debris a force-delete would leave behind.
		profile.flags.ignore_links = True
		profile.save(ignore_permissions=True)

		try:
			offered = self._load()["order_types"]
			self.assertTrue(offered, "a dangling restriction emptied the terminal")
		finally:
			profile.allowed_order_types = []
			for row in original:
				profile.append("allowed_order_types", {"order_type": row.order_type})
			profile.save(ignore_permissions=True)

	def test_the_screen_layout_comes_with_its_buttons(self):
		"""FR-3.5."""
		payload = self._load()
		layout = payload["screen_layout"]
		if not layout:
			self.skipTest("no screen layout assigned to this profile")

		self.assertIn("buttons", layout)
		self.assertIn("grid_columns", layout)

	def test_the_theme_tokens_are_present(self):
		"""FR-15.4 — the Vue app reads colours from here, never from a literal."""
		theme = self._load()["theme"]
		for token in ("primary", "primary_contrast", "surface", "background", "text"):
			self.assertTrue(theme[token].startswith("#"), token)

	def test_the_open_shift_is_reported(self):
		payload = self._load()
		self.assertIsNotNone(payload["active_shift"])
		self.assertEqual(payload["active_shift"]["status"], "open")

	def test_the_menu_brings_its_modifier_groups(self):
		"""D-076 — the popup must not need the network to price an option.

		Scoped to what this terminal's menu can reach, and carrying the options,
		because a group without them cannot be shown or priced.
		"""
		payload = self._load()

		self.assertIn("modifier_groups", payload)
		wanted = {group for item in payload["items"] for group in (item.get("modifier_groups") or [])}
		self.assertEqual({group["name"] for group in payload["modifier_groups"]}, wanted)

		for group in payload["modifier_groups"]:
			self.assertIn("options", group)

	def test_a_closed_drawer_stops_the_terminal_selling(self):
		"""BR-044, D-054 — the screens gate on this, so it must be the real rule.

		`active_shift` is only the day, and it stays open when a cashier hands
		their drawer back. Every screen read that, so closing a till left the
		till still selling.
		"""
		from restaurant_pos.utils import shift as shift_service

		self.assertTrue(self._load()["can_sell"])

		till = shift_service.selling_till(self.profile)
		frappe.db.set_value("POS Opening Entry", till.name, "status", "Closed")
		try:
			payload = self._load()
			self.assertIsNotNone(payload["active_shift"], "the day is still open")
			self.assertFalse(payload["can_sell"], "but there is no drawer to sell into")
		finally:
			frappe.db.set_value("POS Opening Entry", till.name, "status", "Open")

	def test_a_closed_shift_is_reported_as_none(self):
		"""BR-044 — the UI must be able to force an open-shift screen."""
		shift = frappe.db.get_value("POS Profile", self.profile, "restaurant_shift")
		frappe.db.set_value("Restaurant Shift", shift, "status", "closed")
		try:
			self.assertIsNone(self._load()["active_shift"])
		finally:
			frappe.db.set_value("Restaurant Shift", shift, "status", "open")

	def test_loading_does_not_scale_queries_with_the_menu(self):
		"""04 §8 — login is the slowest screen; it must not be O(items)."""
		calls = 0
		real_get_all = frappe.get_all

		def counting(*args, **kwargs):
			nonlocal calls
			calls += 1
			return real_get_all(*args, **kwargs)

		frappe.get_all = counting
		try:
			self._load()
			baseline = calls
		finally:
			frappe.get_all = real_get_all

		# Add ten more items and confirm the query count is unchanged.
		group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
		for index in range(10):
			code = f"RPOS-TEST-BULK-{index}"
			if not frappe.db.exists("Item", code):
				frappe.get_doc(
					{
						"doctype": "Item",
						"item_code": code,
						"item_name": code,
						"item_group": group,
						"stock_uom": "Nos",
						"is_stock_item": 0,
					}
				).insert(ignore_permissions=True)

		calls = 0
		frappe.get_all = counting
		try:
			self._load()
			with_more_items = calls
		finally:
			frappe.get_all = real_get_all

		self.assertEqual(
			with_more_items,
			baseline,
			"load_pos_session issued more queries for a bigger menu — N+1",
		)


class TestPing(OrderTestBase):
	def test_ping_answers(self):
		"""09 §2 — the sync engine reads a slow or failed answer as an outage."""
		result = session.ping()
		self.assertEqual(result["status"], "ok")
		self.assertIn("timestamp", result)


class TestTheScreenLayoutMode(FrappeTestCase):
	"""What a layout's coordinates mean, and when they mean nothing (`D-141`).

	`flow` is the mode a restaurant should use: the buttons go down in the order
	a manager dragged them into, and `col_start` is a number nobody has to
	invent. `grid` is for a screen somebody deliberately drew.

	The mode has to reach the terminal or the till cannot tell them apart — and
	the failure would be silent, because a flow layout rendered on a grid still
	draws *something*.
	"""

	def _layout(self, mode: str) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "POS Screen Layout",
				"title": f"RPOS Test {mode}",
				"layout_mode": mode,
				"grid_columns": 4,
				"grid_rows": 3,
				"is_active": 1,
				"buttons": [
					{
						"button_type": "item_group",
						"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
						"col_start": 1,
						"col_span": 1,
						"row_start": 1,
						"row_span": 1,
					}
				],
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "POS Screen Layout", doc.name, force=True)
		return doc.name

	def test_the_mode_reaches_the_terminal(self):
		from restaurant_pos.api.session import _screen_layout

		self.assertEqual(_screen_layout(self._layout("flow"))["layout_mode"], "flow")
		self.assertEqual(_screen_layout(self._layout("grid"))["layout_mode"], "grid")

	def test_a_new_layout_flows_by_default(self):
		"""Nobody should have to choose the mode to get the easy one."""
		doc = frappe.get_doc(
			{"doctype": "POS Screen Layout", "title": "RPOS Test default", "is_active": 1}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "POS Screen Layout", doc.name, force=True)

		self.assertEqual(doc.layout_mode, "flow")

	def test_a_flow_layout_takes_a_second_button_without_a_quarrel(self):
		"""The defect the user found within a minute of being handed this.

		Every coordinate field defaults to 1, and the grid rules were still on
		in flow — so adding a second row was refused with "Cell (column 1, row
		1) is already used by row #1", about a grid the form does not show and
		the till does not read. Hiding the fields and ignoring them in the
		renderer was half a change (`D-142`).
		"""
		group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
		doc = frappe.get_doc(
			{
				"doctype": "POS Screen Layout",
				"title": "RPOS Test crowded flow",
				"layout_mode": "flow",
				"buttons": [
					{"button_type": "item_group", "item_group": group},
					{"button_type": "item_group", "item_group": group},
					{"button_type": "item_group", "item_group": group},
				],
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "POS Screen Layout", doc.name, force=True)

		self.assertEqual(len(doc.buttons), 3)
		self.assertEqual([row.idx for row in doc.buttons], [1, 2, 3])

	def test_a_grid_layout_still_refuses_two_buttons_in_one_cell(self):
		"""The rule is right where it applies — it was only in the wrong place."""
		group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")

		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "POS Screen Layout",
					"title": "RPOS Test collision",
					"layout_mode": "grid",
					"grid_columns": 4,
					"grid_rows": 4,
					"buttons": [
						{"button_type": "item_group", "item_group": group},
						{"button_type": "item_group", "item_group": group},
					],
				}
			).insert(ignore_permissions=True)

	def test_a_flow_layout_needs_no_grid_size(self):
		"""The point of the mode: no numbers to invent."""
		doc = frappe.get_doc(
			{"doctype": "POS Screen Layout", "title": "RPOS Test sizeless", "layout_mode": "flow"}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "POS Screen Layout", doc.name, force=True)

		self.assertTrue(doc.name)

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Tests for the permission, override and audit layer.

Refs: 08_Security.md §§3-5, FR-12.3, FR-12.6, FR-12.7, FR-12.8
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from restaurant_pos.setup.defaults import PERMISSION_SETS, create_default_data
from restaurant_pos.utils import manager_pin as pins
from restaurant_pos.utils import permissions as perms
from restaurant_pos.utils.audit import log_audit, redact

CASHIER = "rpos_test_cashier@example.com"
SENIOR = "rpos_test_senior@example.com"
MANAGER = "rpos_test_manager@example.com"


def _make_user(email: str, role: str) -> str:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
	else:
		user = frappe.get_doc("User", email)

	existing = {r.role for r in user.roles}
	if role not in existing:
		user.append("roles", {"role": role})
		user.save(ignore_permissions=True)

	return email


def _reset_to_shipped_defaults(role: str) -> None:
	"""Put a permission set back to the values the app ships with.

	Defaults are deliberately never re-applied after install (D-013), so a site
	that has been configured — or poked at by an earlier test — would otherwise
	make these assertions depend on state the test does not own.
	"""
	doc = frappe.get_doc("POS Permission Set", role)
	doc.update(PERMISSION_SETS[role])
	doc.save(ignore_permissions=True)


class TestPermissionResolution(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		create_default_data()
		_reset_to_shipped_defaults("POS Cashier")
		_reset_to_shipped_defaults("POS Manager")
		_make_user(CASHIER, "POS Cashier")
		_make_user(MANAGER, "POS Manager")
		frappe.db.commit()

	def setUp(self):
		frappe.local.rpos_permission_cache = {}

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.rpos_permission_cache = {}

	def test_cashier_defaults_match_the_spec(self):
		"""08 §3: a cashier may void an item but not an order, and gets no discount."""
		permissions = perms.get_pos_permission_set(CASHIER)

		self.assertEqual(permissions.can_void_item, 1)
		self.assertEqual(permissions.can_void_order, 0)
		self.assertEqual(permissions.max_item_discount_pct, 0)
		self.assertEqual(permissions.can_close_others_shift, 0)

	def test_manager_outranks_cashier(self):
		self.assertGreater(perms.user_rank(MANAGER), perms.user_rank(CASHIER))

	def test_permission_set_never_exposes_the_pin(self):
		"""CLAUDE.md §5.4: manager_pin must not appear in any response."""
		for user in (CASHIER, MANAGER):
			permissions = perms.get_pos_permission_set(user)
			self.assertNotIn("manager_pin", permissions)

	def test_roles_merge_to_the_most_permissive(self):
		"""A user holding two roles gets the union, not the last one read."""
		email = _make_user("rpos_test_dual@example.com", "POS Cashier")
		user = frappe.get_doc("User", email)
		if "POS Manager" not in {r.role for r in user.roles}:
			user.append("roles", {"role": "POS Manager"})
			user.save(ignore_permissions=True)
		frappe.local.rpos_permission_cache = {}

		permissions = perms.get_pos_permission_set(email)
		self.assertEqual(permissions.can_cancel_order, 1)
		self.assertEqual(permissions.max_order_discount_pct, 50)

	def test_assert_permission_blocks_and_allows(self):
		perms.assert_permission("can_void_item", CASHIER)

		with self.assertRaises(frappe.PermissionError):
			perms.assert_permission("can_void_order", CASHIER)

	def test_discount_ceiling_is_enforced(self):
		"""BR-031."""
		perms.assert_within_discount_limit("max_order_discount_pct", 25, MANAGER)

		with self.assertRaises(frappe.PermissionError):
			perms.assert_within_discount_limit("max_order_discount_pct", 75, MANAGER)

		with self.assertRaises(frappe.PermissionError):
			perms.assert_within_discount_limit("max_order_discount_pct", 1, CASHIER)


class TestPrivilegeEscalationGuard(FrappeTestCase):
	"""FR-12.6 — the four rules."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		create_default_data()
		_make_user(CASHIER, "POS Cashier")
		_make_user(MANAGER, "POS Manager")
		_make_user(SENIOR, "POS Senior Cashier")
		frappe.db.commit()

	def setUp(self):
		frappe.local.rpos_permission_cache = {}

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.rpos_permission_cache = {}

	def test_cannot_grant_a_permission_you_lack(self):
		"""Rule 1. A senior cashier cannot void orders, so cannot grant that right.

		The actor must genuinely lack the permission, otherwise the rejection
		would come from the rank check and this would test rule 3 twice.
		"""
		self.assertEqual(perms.get_pos_permission_set(SENIOR).can_void_order, 0)

		frappe.set_user(SENIOR)
		with self.assertRaises(frappe.PermissionError):
			perms.assert_may_edit_permission_set("POS Cashier", {"can_void_order": 1})

	def test_may_grant_a_permission_you_do_hold(self):
		"""The mirror of rule 1 — the guard must not block legitimate edits."""
		frappe.set_user(SENIOR)
		changes = perms.assert_may_edit_permission_set("POS Cashier", {"can_create_return": 1})
		self.assertEqual(changes["can_create_return"]["after"], 1)

	def test_cannot_edit_a_role_at_or_above_your_rank(self):
		frappe.set_user(MANAGER)

		with self.assertRaises(frappe.PermissionError):
			perms.assert_may_edit_permission_set("POS Manager", {"can_void_item": 1})

		with self.assertRaises(frappe.PermissionError):
			perms.assert_may_edit_permission_set("Restaurant Admin", {"can_void_item": 1})

	def test_cannot_raise_a_ceiling_above_your_own(self):
		frappe.set_user(MANAGER)
		with self.assertRaises(frappe.PermissionError):
			perms.assert_may_edit_permission_set("POS Cashier", {"max_item_discount_pct": 90})

	def test_may_edit_a_lower_role_within_your_own_limits(self):
		frappe.set_user(MANAGER)
		changes = perms.assert_may_edit_permission_set(
			"POS Cashier", {"max_item_discount_pct": 5, "can_void_item": 1}
		)
		self.assertEqual(changes["max_item_discount_pct"]["after"], 5)
		self.assertNotIn("can_void_item", changes)  # already 1, so not a change

	def test_cannot_assign_a_role_to_yourself(self):
		frappe.set_user(MANAGER)
		with self.assertRaises(frappe.PermissionError):
			perms.assert_may_assign_role("POS Cashier", MANAGER)

	def test_cannot_assign_a_role_at_or_above_your_rank(self):
		frappe.set_user(MANAGER)
		with self.assertRaises(frappe.PermissionError):
			perms.assert_may_assign_role("Restaurant Admin", CASHIER)


class TestManagerPin(FrappeTestCase):
	"""The PIN identifies a person, not a role (D-016)."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		create_default_data()
		_make_user(CASHIER, "POS Cashier")
		_make_user(MANAGER, "POS Manager")
		pins.set_pin(MANAGER, "42715")
		frappe.db.commit()

	def test_correct_pin_identifies_the_person_who_approved(self):
		"""The whole point of the move: approved_by names a human."""
		self.assertEqual(pins.find_approver_for_pin("can_void_order", "42715"), MANAGER)

	def test_wrong_pin_finds_nothing(self):
		self.assertIsNone(pins.find_approver_for_pin("can_void_order", "00000"))

	def test_pin_does_not_authorise_an_action_its_holder_lacks(self):
		"""A valid PIN is not a master key."""
		pins.set_pin(CASHIER, "13579")
		frappe.local.rpos_permission_cache = {}

		self.assertEqual(pins.find_approver_for_pin("can_void_item", "13579"), CASHIER)
		self.assertIsNone(pins.find_approver_for_pin("can_void_order", "13579"))

	def test_pin_is_never_stored_reversibly(self):
		"""D-015: a Password DocField would be readable with the site key."""
		auth = frappe.qb.Table("__Auth")
		rows = (
			frappe.qb.from_(auth)
			.select(auth.encrypted, auth.password)
			.where((auth.doctype == "User") & (auth.name == MANAGER) & (auth.fieldname == pins.FIELDNAME))
			.run()
		)
		self.assertTrue(rows)
		for encrypted, stored in rows:
			self.assertEqual(encrypted, 0)
			self.assertNotIn("42715", str(stored))

	def test_has_pin_reports_without_reading(self):
		self.assertTrue(pins.has_pin(MANAGER))
		self.assertFalse(pins.has_pin("Administrator"))

	def test_two_users_cannot_share_a_pin(self):
		"""A shared PIN would make approved_by name the wrong person."""
		with self.assertRaises(frappe.ValidationError):
			pins.set_pin(CASHIER, "42715")

	def test_pin_must_be_five_digits(self):
		"""Five since the PIN became an identity as well as an approval (D-094)."""
		for bad in ("1234", "123456", "abcde", "12a45", ""):
			with self.assertRaises(frappe.ValidationError):
				pins.set_pin(CASHIER, bad)

	def test_clearing_a_pin_revokes_approval(self):
		pins.set_pin(CASHIER, "24680")
		self.assertTrue(pins.has_pin(CASHIER))

		pins.clear_pin(CASHIER)
		self.assertFalse(pins.has_pin(CASHIER))
		self.assertIsNone(pins.find_approver_for_pin("can_void_item", "24680"))

	def test_a_cashier_cannot_overwrite_a_managers_pin(self):
		frappe.set_user(CASHIER)
		try:
			with self.assertRaises(frappe.PermissionError):
				perms.assert_may_manage_pin_of(MANAGER)
			perms.assert_may_manage_pin_of(CASHIER)  # own PIN is fine
		finally:
			frappe.set_user("Administrator")


class TestOverrideToken(FrappeTestCase):
	"""07 §7 — single use, bound to one action and one user."""

	def test_token_round_trip(self):
		token = perms.issue_override_token("can_void_order", MANAGER)
		self.assertEqual(perms.consume_override_token(token, "can_void_order"), MANAGER)

	def test_token_is_single_use(self):
		token = perms.issue_override_token("can_void_order", MANAGER)
		perms.consume_override_token(token, "can_void_order")

		with self.assertRaises(frappe.PermissionError):
			perms.consume_override_token(token, "can_void_order")

	def test_token_is_bound_to_its_action(self):
		token = perms.issue_override_token("can_void_order", MANAGER)
		with self.assertRaises(frappe.PermissionError):
			perms.consume_override_token(token, "can_cancel_order")

	def test_token_is_bound_to_the_user_who_requested_it(self):
		token = perms.issue_override_token("can_void_order", MANAGER)
		frappe.set_user(CASHIER)
		try:
			with self.assertRaises(frappe.PermissionError):
				perms.consume_override_token(token, "can_void_order")
		finally:
			frappe.set_user("Administrator")

	def test_missing_token_is_rejected(self):
		with self.assertRaises(frappe.PermissionError):
			perms.consume_override_token("", "can_void_order")

		with self.assertRaises(frappe.PermissionError):
			perms.consume_override_token("not-a-real-token", "can_void_order")


class TestAudit(FrappeTestCase):
	"""08 §5 and FR-12.7."""

	def test_credentials_are_redacted_at_every_depth(self):
		payload = {
			"pin": "1234",
			"manager_pin": "1234",
			"api_key": "abc",
			"nested": {"password": "hunter2", "qty": 3},
			"rows": [{"token": "xyz", "item": "BURGER"}],
			"item": "BURGER",
		}
		clean = redact(payload)

		self.assertEqual(clean["pin"], "***")
		self.assertEqual(clean["manager_pin"], "***")
		self.assertEqual(clean["api_key"], "***")
		self.assertEqual(clean["nested"]["password"], "***")
		self.assertEqual(clean["rows"][0]["token"], "***")

		# Non-credential data must survive untouched.
		self.assertEqual(clean["nested"]["qty"], 3)
		self.assertEqual(clean["rows"][0]["item"], "BURGER")
		self.assertEqual(clean["item"], "BURGER")

	def test_log_audit_writes_an_entry_and_redacts(self):
		branch = frappe.db.get_value("Branch", {}, "name")
		profile = frappe.db.get_value("POS Profile", {}, "name")
		if not (branch and profile):
			self.skipTest("no Branch/POS Profile on this site")

		name = log_audit(
			"void_item",
			branch=branch,
			pos_profile=profile,
			reason="test",
			details={"pin": "9999", "item": "BURGER"},
		)

		entry = frappe.get_doc("POS Audit Log", name)
		details = frappe.parse_json(entry.details)
		self.assertEqual(details["pin"], "***")
		self.assertEqual(details["item"], "BURGER")
		self.assertEqual(entry.cashier, frappe.session.user)

	def _new_entry(self, reason: str) -> str:
		branch = frappe.db.get_value("Branch", {}, "name")
		profile = frappe.db.get_value("POS Profile", {}, "name")
		if not (branch and profile):
			self.skipTest("no Branch/POS Profile on this site")

		return log_audit("void_item", branch=branch, pos_profile=profile, reason=reason)

	def test_audit_entries_cannot_be_modified(self):
		name = self._new_entry("original")

		entry = frappe.get_doc("POS Audit Log", name)
		entry.reason = "tampered"
		with self.assertRaises(frappe.PermissionError):
			entry.save(ignore_permissions=True)

		self.assertEqual(frappe.db.get_value("POS Audit Log", name, "reason"), "original")

	def test_audit_entries_cannot_be_deleted(self):
		# A separate entry, because rolling back between the two assertions would
		# remove the row and delete_doc would then no-op instead of refusing.
		name = self._new_entry("to delete")

		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc("POS Audit Log", name, force=True, ignore_permissions=True)

		self.assertTrue(frappe.db.exists("POS Audit Log", name))

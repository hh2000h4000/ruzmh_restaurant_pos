# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Moving lines between bills — one primitive, two operations (BR-067).

Splitting moves lines onto a **new** order; merging moves all of them onto an
**existing** one and closes the empty document. Written twice, "take this line
off that bill and put it on this one" is how two bills stop adding up to what
was eaten — so both go through `move_items`.

**The kitchen is never told.** A line already sent keeps its ticket reference
and its `sent` status, and nothing new is printed: the food is on the pass, it
goes to the table rather than to the bill, and re-firing it would cook it twice.
That is what the tests here are mostly checking, because it is the part that
looks wrong until you think about where the plate actually goes.

Refs: BR-067, FR-2.12, D-058, D-119
"""

import frappe

from restaurant_pos.tests.test_order import BRANCH, ITEM, OrderTestBase, free_table
from restaurant_pos.utils import order as service


class MovingLinesBetweenBills(OrderTestBase):
	def setUp(self):
		self.allowed = frappe.db.get_value("Branch", BRANCH, "allow_multiple_orders_per_table")
		self.table = frappe.db.get_value(
			"Restaurant Table", {"section": self.section, "is_active": 1}, "name"
		)
		frappe.set_user("Administrator")
		free_table(self.table)
		frappe.db.commit()

	def tearDown(self):
		frappe.db.set_value("Branch", BRANCH, "allow_multiple_orders_per_table", self.allowed)
		frappe.clear_cache(doctype="Branch")
		free_table(self.table)
		frappe.db.commit()

	def _allow_two_bills(self, allowed: bool = True) -> None:
		frappe.db.set_value("Branch", BRANCH, "allow_multiple_orders_per_table", 1 if allowed else 0)
		frappe.clear_cache(doctype="Branch")

	def _bill(self, *quantities):
		"""A takeaway with one line per quantity given."""
		order = self._order()
		for qty in quantities:
			service.add_item(order, item=ITEM, qty=qty)
		order.save(ignore_permissions=True)
		order.reload()
		return order

	# ------------------------------------------------------------------ #
	# The primitive
	# ------------------------------------------------------------------ #

	def test_a_whole_line_moves_across(self):
		source = self._bill(1, 2)
		target = self._bill(1)
		moving = source.items[0]

		service.move_items(source, target, [{"idx": moving.idx}])

		self.assertEqual(len(source.items), 1)
		self.assertEqual(len(target.items), 2)
		self.assertEqual(target.items[1].item, moving.item)

	def test_the_two_bills_still_add_up_to_what_was_eaten(self):
		"""The property that matters: nothing is created or lost in the move."""
		source = self._bill(1, 2, 3)
		target = self._bill(1)
		before = float(source.total_amount) + float(target.total_amount)

		service.move_items(source, target, [{"idx": source.items[0].idx}])

		after = float(source.total_amount) + float(target.total_amount)
		self.assertAlmostEqual(after, before, places=2)

	def test_part_of_a_line_can_move(self):
		"""Two people sharing a "2 x cola" line is the ordinary case."""
		source = self._bill(2)
		target = self._bill(1)
		line = source.items[0]
		rate = float(line.rate)

		service.move_items(source, target, [{"idx": line.idx, "qty": 1}])

		source.reload()
		target.reload()
		self.assertEqual(float(source.items[0].qty), 1)
		self.assertAlmostEqual(float(source.items[0].amount), rate, places=2)
		self.assertAlmostEqual(float(target.items[1].amount), rate, places=2)

	def test_more_than_the_line_holds_is_refused(self):
		source = self._bill(2)
		target = self._bill(1)

		with self.assertRaises(frappe.ValidationError):
			service.move_items(source, target, [{"idx": source.items[0].idx, "qty": 3}])

	def test_a_bill_cannot_be_split_into_itself(self):
		bill = self._bill(1)
		with self.assertRaises(frappe.ValidationError):
			service.move_items(bill, bill, [{"idx": bill.items[0].idx}])

	def test_nothing_selected_is_refused(self):
		source = self._bill(1)
		target = self._bill(1)
		with self.assertRaises(frappe.ValidationError):
			service.move_items(source, target, [])

	# ------------------------------------------------------------------ #
	# The kitchen
	# ------------------------------------------------------------------ #

	def test_a_line_already_cooking_keeps_its_ticket(self):
		"""The rule that looks wrong until you think about it: the plate goes to
		the table, not to the bill. Splitting a check fires nothing."""
		from restaurant_pos.utils import kitchen

		source = self._bill(1)
		target = self._bill(1)
		kitchen.send_to_kitchen(source)
		source.reload()

		line = source.items[0]
		self.assertEqual(line.status, "sent")
		ticket = line.kot_reference

		tickets_before = frappe.db.count("Kitchen Order Ticket")
		service.move_items(source, target, [{"idx": line.idx}])
		target.reload()

		carried = target.items[-1]
		self.assertEqual(carried.status, "sent")
		self.assertEqual(carried.kot_reference, ticket)
		self.assertEqual(frappe.db.count("Kitchen Order Ticket"), tickets_before)

	# ------------------------------------------------------------------ #
	# What it refuses, and why
	# ------------------------------------------------------------------ #

	def test_a_discounted_bill_is_refused(self):
		"""An order-level discount has no honest share — the same reasoning `02`
		§233 applies to returns."""
		source = self._bill(2)
		target = self._bill(1)
		frappe.db.set_value("Restaurant Order", source.name, "discount_amount", 5)
		source.reload()

		with self.assertRaises(frappe.ValidationError):
			service.move_items(source, target, [{"idx": source.items[0].idx}])

	def test_two_different_order_types_are_refused(self):
		"""Prices follow the order type, so a line carried across would keep a
		rate the receiving bill does not sell at."""
		source = self._bill(1)
		target = self._order(order_type=self.dine_in, table=self.table, cover_count=2)
		service.add_item(target, item=ITEM, qty=1)
		target.save(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			service.move_items(source, target, [{"idx": source.items[0].idx}])

	def test_a_voided_line_does_not_move(self):
		source = self._bill(1, 1)
		target = self._bill(1)
		frappe.db.set_value(
			"Restaurant Order Item", source.items[0].name, "status", "void", update_modified=False
		)
		source.reload()

		with self.assertRaises(frappe.ValidationError):
			service.move_items(source, target, [{"idx": source.items[0].idx}])

	# ------------------------------------------------------------------ #
	# Splitting
	# ------------------------------------------------------------------ #

	def test_splitting_makes_a_second_bill_with_its_own_number(self):
		source = self._bill(1, 1)

		outcome = service.split_order(source, [{"idx": source.items[0].idx}])

		second = frappe.get_doc("Restaurant Order", outcome["target"])
		self.assertNotEqual(second.daily_number, source.daily_number)
		self.assertEqual(len(second.items), 1)
		self.assertEqual(len(source.items), 1)

	def test_a_seated_bill_cannot_be_split_where_a_table_takes_one_bill(self):
		"""And the cashier is told that, rather than "table 4 is occupied" from
		a rule they were not thinking about."""
		self._allow_two_bills(False)
		source = self._order(order_type=self.dine_in, table=self.table, cover_count=2)
		service.add_item(source, item=ITEM, qty=2)
		source.save(ignore_permissions=True)
		source.reload()

		with self.assertRaises(frappe.ValidationError):
			service.split_order(source, [{"idx": source.items[0].idx}])

	def test_a_seated_bill_splits_where_the_branch_allows_two(self):
		self._allow_two_bills(True)
		source = self._order(order_type=self.dine_in, table=self.table, cover_count=2)
		service.add_item(source, item=ITEM, qty=2)
		source.save(ignore_permissions=True)
		source.reload()

		outcome = service.split_order(source, [{"idx": source.items[0].idx, "qty": 1}])

		self.assertEqual(len(service.open_orders_on(self.table)), 2)
		self.assertIn(outcome["target"], service.open_orders_on(self.table))

	# ------------------------------------------------------------------ #
	# Merging
	# ------------------------------------------------------------------ #

	def test_merging_empties_one_bill_and_closes_it(self):
		source = self._bill(1, 2)
		target = self._bill(1)

		outcome = service.merge_orders(source, target)

		target.reload()
		self.assertEqual(len(target.items), 3)
		self.assertEqual(outcome["merged"], source.name)
		self.assertEqual(frappe.db.get_value("Restaurant Order", source.name, "status"), "cancelled")

	def test_merging_says_where_the_bill_went(self):
		"""An emptied bill that just says "cancelled" is a bill nobody can
		account for at closing."""
		source = self._bill(1)
		target = self._bill(1)

		service.merge_orders(source, target)

		self.assertIn(target.name, frappe.db.get_value("Restaurant Order", source.name, "cancel_reason"))

	def test_an_empty_bill_has_nothing_to_merge(self):
		source = self._order()
		target = self._bill(1)

		with self.assertRaises(frappe.ValidationError):
			service.merge_orders(source, target)

	# ------------------------------------------------------------------ #
	# The trail
	# ------------------------------------------------------------------ #

	def test_both_bills_carry_the_move_in_their_history(self):
		"""A bill that gained three dishes with nothing to say where they came
		from is the question this log exists to answer."""
		source = self._bill(1)
		target = self._bill(1)

		service.move_items(source, target, [{"idx": source.items[0].idx}])

		self.assertTrue(
			frappe.db.exists(
				"POS Order Activity", {"restaurant_order": source.name, "action": "items_moved_out"}
			)
		)
		self.assertTrue(
			frappe.db.exists(
				"POS Order Activity", {"restaurant_order": target.name, "action": "items_moved_in"}
			)
		)

	def test_the_move_is_audited(self):
		source = self._bill(1)
		target = self._bill(1)

		service.move_items(source, target, [{"idx": source.items[0].idx}])

		self.assertTrue(
			frappe.db.exists("POS Audit Log", {"restaurant_order": source.name, "action_type": "bill_split"})
		)


class ThePreviewMatchesTheSplit(OrderTestBase):
	"""The split screen shows a running total per side, and a total is money.

	So the server prices both sides before anything moves (`CLAUDE.md` §5.1) —
	the same reason `preview_totals` exists for a discount. A figure a cashier
	reads to a customer has to be the figure the invoice will carry, which means
	the preview and the split itself must agree exactly.
	"""

	def _bill(self, *quantities):
		order = self._order()
		for qty in quantities:
			service.add_item(order, item=ITEM, qty=qty)
		order.save(ignore_permissions=True)
		order.reload()
		return order

	def test_the_two_sides_add_up_to_the_bill(self):
		order = self._bill(1, 2, 3)
		before = float(order.total_amount)

		preview = service.preview_split(order, [{"idx": order.items[0].idx}])

		self.assertAlmostEqual(
			preview["source"]["total_amount"] + preview["target"]["total_amount"], before, places=2
		)

	def test_a_part_line_is_priced_per_unit(self):
		order = self._bill(2)
		rate = float(order.items[0].rate)

		preview = service.preview_split(order, [{"idx": order.items[0].idx, "qty": 1}])

		self.assertAlmostEqual(preview["target"]["subtotal"], rate, places=2)
		self.assertAlmostEqual(preview["source"]["subtotal"], rate, places=2)

	def test_it_matches_what_the_split_actually_does(self):
		"""The property that makes the preview worth showing at all."""
		order = self._bill(1, 2)
		rows = [{"idx": order.items[0].idx}]

		preview = service.preview_split(order, rows)
		outcome = service.split_order(order, rows)

		order.reload()
		target = frappe.get_doc("Restaurant Order", outcome["target"])
		self.assertAlmostEqual(float(order.total_amount), preview["source"]["total_amount"], places=2)
		self.assertAlmostEqual(float(target.total_amount), preview["target"]["total_amount"], places=2)

	def test_moving_nothing_leaves_the_bill_whole(self):
		order = self._bill(1, 1)

		preview = service.preview_split(order, [])

		self.assertAlmostEqual(preview["source"]["total_amount"], float(order.total_amount), places=2)
		self.assertEqual(preview["target"]["total_amount"], 0)

	def test_it_refuses_what_the_move_would_refuse(self):
		"""Told at the moment of the tap, not after the whole bill is arranged."""
		order = self._bill(1)

		with self.assertRaises(frappe.ValidationError):
			service.preview_split(order, [{"idx": order.items[0].idx, "qty": 5}])


class ABillWithFoodOnItIsNotADraft(OrderTestBase):
	"""A draft is an **empty** bill, and moving a line onto one ends that.

	`add_item` has always promoted a draft to `active` on the first line.
	`move_items` did not, so the second bill of every split sat in the orders
	list saying "draft" with a dish on it. The user found it by asking what the
	difference between the drafts tab and the open tab was — the answer being
	that this bill was in the wrong one.

	Refs: BR-067, D-122
	"""

	def _bill(self, *quantities):
		order = self._order()
		for qty in quantities:
			service.add_item(order, item=ITEM, qty=qty)
		order.save(ignore_permissions=True)
		order.reload()
		return order

	def test_splitting_leaves_the_new_bill_active(self):
		source = self._bill(1, 1)

		outcome = service.split_order(source, [{"idx": source.items[0].idx}])

		self.assertEqual(frappe.db.get_value("Restaurant Order", outcome["target"], "status"), "active")

	def test_a_draft_that_receives_a_line_stops_being_one(self):
		source = self._bill(1)
		target = self._order()  # nothing on it: a real draft
		self.assertEqual(target.status, "draft")

		service.move_items(source, target, [{"idx": source.items[0].idx}])

		self.assertEqual(target.status, "active")

	def test_a_line_already_cooking_still_carries_the_kitchen(self):
		"""The promotion must not overwrite the stronger status."""
		from restaurant_pos.utils import kitchen

		source = self._bill(1)
		kitchen.send_to_kitchen(source)
		source.reload()
		target = self._order()

		service.move_items(source, target, [{"idx": source.items[0].idx}])

		self.assertEqual(target.status, "in_kitchen")

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""A combo is sold as its items — to the kitchen, to the invoice, to stock (`D-285`).

«Burger meal»: the burger of `test_recipes` always, and a drink chosen — cola
(5.00) by default, or juice, which adds 3.00 to a fixed-price meal. Every
figure is known, so the tests hold the till's price, the invoice's shares, the
warehouse and the return to it.

Refs: FR-4.2, D-284, D-285
"""

import frappe
from frappe.utils import flt

from restaurant_pos.api import session
from restaurant_pos.tests.test_order import BRANCH, ITEM, TEST_ITEM_RATE, TEST_PRICE_LIST
from restaurant_pos.tests.test_recipes import COST_OF_ONE, RecipeTestBase
from restaurant_pos.utils import combos, kitchen, posting, returns
from restaurant_pos.utils import order as orders
from restaurant_pos.utils.sale_doc import SALE_ITEM

MEAL = "RPOS-TEST-CMB-MEAL"
COLA = "RPOS-TEST-CMB-COLA"
JUICE = "RPOS-TEST-CMB-JUICE"
MEAL_PRICE = 29.00
COLA_PRICE = 5.00
JUICE_PRICE = 7.00
UPGRADE = 3.00
DRINK = "Drink"


def _choice(name: str, low: int = 1, high: int = 1) -> str:
	"""A combo choice picking between ``low`` and ``high`` items (`D-290`)."""
	if frappe.db.exists("POS Combo Choice", name):
		frappe.db.set_value("POS Combo Choice", name, {"min_selections": low, "max_selections": high})
	else:
		frappe.get_doc(
			{
				"doctype": "POS Combo Choice",
				"title_ar": name,
				"title": name,
				"min_selections": low,
				"max_selections": high,
			}
		).insert(ignore_permissions=True)
	return name


class ComboTestBase(RecipeTestBase):
	def setUp(self):
		super().setUp()
		_choice(DRINK)
		for code, price in ((COLA, COLA_PRICE), (JUICE, JUICE_PRICE)):
			self._ingredient(code, "Nos")
			self._receive(code, 50, 1.00)
			self._price(code, price)
		self._meal("fixed")

	def _price(self, code: str, rate: float) -> None:
		frappe.db.delete("Item Price", {"item_code": code, "price_list": TEST_PRICE_LIST})
		frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": code,
				"price_list": TEST_PRICE_LIST,
				"price_list_rate": rate,
			}
		).insert(ignore_permissions=True)

	def _meal(self, pricing: str) -> None:
		rows = [
			{"slot": "", "item": ITEM, "qty": 1, "price_source": "item_price"},
			{"slot": DRINK, "item": COLA, "qty": 1, "price_source": "item_price", "is_default": 1},
			{
				"slot": DRINK,
				"item": JUICE,
				"qty": 1,
				"price_source": "item_price" if pricing == "sum" else "amount",
				"price": UPGRADE,
				"adds_to_price": 1,
			},
		]
		if frappe.db.exists("Item", MEAL):
			meal = frappe.get_doc("Item", MEAL)
			meal.rpos_combo_pricing = pricing
			meal.set("rpos_combo_items", rows)
			meal.save(ignore_permissions=True)
		else:
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": MEAL,
					"item_name": "Burger meal",
					"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
					"stock_uom": "Nos",
					"is_stock_item": 0,
					"rpos_is_combo": 1,
					"rpos_combo_pricing": pricing,
					"rpos_combo_items": rows,
				}
			).insert(ignore_permissions=True)
		self._price(MEAL, MEAL_PRICE)

	def _ordered(self, drink: str, qty: float = 1):
		order = self._order()
		orders.add_item(
			order, item=MEAL, qty=qty, modifiers=[{"group": combos.group_name(MEAL, DRINK), "option": drink}]
		)
		order.reload()
		return order

	def _paid(self, drink: str, qty: float = 1):
		order = self._ordered(drink, qty)
		self._pay(order)
		order.reload()
		return order

	def _lines(self, invoice: str) -> list:
		return frappe.get_all(
			SALE_ITEM,
			filters={"parent": invoice},
			fields=["name", "item_code", "qty", "rate", "amount", "rpos_combo", "is_free_item"],
			order_by="idx",
		)


class AFixedPriceCombo(ComboTestBase):
	def test_the_till_prices_the_meal_and_an_upgrade_adds_on_top(self):
		self.assertEqual(flt(self._ordered(COLA).items[0].amount), MEAL_PRICE)
		self.assertEqual(flt(self._ordered(JUICE).items[0].amount), MEAL_PRICE + UPGRADE)

	def test_the_invoice_sells_the_items_sharing_the_price_by_their_own(self):
		order = self._paid(COLA, qty=2)
		burger, cola = self._lines(order.sales_invoice)

		self.assertEqual((burger.item_code, cola.item_code), (ITEM, COLA))
		self.assertEqual((burger.rpos_combo, cola.rpos_combo), (MEAL, MEAL))
		whole = TEST_ITEM_RATE + COLA_PRICE
		self.assertAlmostEqual(flt(burger.rate), flt(MEAL_PRICE * TEST_ITEM_RATE / whole, 2), places=2)
		# The shares add up to the meal, to the halala.
		self.assertAlmostEqual(flt(burger.amount) + flt(cola.amount), 2 * MEAL_PRICE, places=2)
		self.assertNotIn(MEAL, [line.item_code for line in self._lines(order.sales_invoice)])

	def test_the_items_leave_the_warehouse_and_the_meal_does_not(self):
		order = self._paid(COLA, qty=2)
		moved = self._moved(order.sales_invoice)

		self.assertEqual(moved[COLA], -2)
		self.assertEqual(moved["RPOS-TEST-PATTY"], -0.3)
		self.assertNotIn(MEAL, moved)
		cost = self._cost(order.sales_invoice)
		self.assertAlmostEqual(cost, 2 * (COST_OF_ONE + 1.00), places=2)

	def test_each_item_reaches_the_kitchen_saying_which_meal_it_is_from(self):
		order = self._ordered(COLA)
		result = kitchen.send_to_kitchen(order)

		sent = [
			row
			for ticket in result["kots_created"]
			for row in frappe.get_all(
				"KOT Item", filters={"parent": ticket["kot_name"]}, fields=["item", "notes"]
			)
		]
		# Two items, each on a ticket — a station's, or the cashier printer's (`D-300`).
		self.assertEqual(len(sent), 2)
		self.assertLessEqual({row.item for row in sent}, {ITEM, COLA})
		for row in sent:
			self.assertIn("Burger meal", row.notes or "")

	def test_an_upgrade_stays_on_the_item_it_upgraded(self):
		"""Juice instead of cola is the juice's +3 — not shared into the burger."""
		order = self._paid(JUICE)
		lines = {line.item_code: flt(line.rate) for line in self._lines(order.sales_invoice)}

		whole = TEST_ITEM_RATE + JUICE_PRICE
		self.assertAlmostEqual(lines[ITEM], flt(MEAL_PRICE * TEST_ITEM_RATE / whole, 2), places=2)
		self.assertAlmostEqual(lines[JUICE], MEAL_PRICE - lines[ITEM] + UPGRADE, places=2)

	def test_a_note_changed_after_the_kitchen_reaches_every_station(self):
		"""Its tickets name the items, so the note was looked up on the combo and lost."""
		grill = frappe.db.get_value("Production Center", {"title": "RPOS Test Grill"}, "name")
		for item in (ITEM, COLA):
			before = frappe.db.get_value("Item", item, "default_production_center")
			frappe.db.set_value("Item", item, "default_production_center", grill)
			self.addCleanup(frappe.db.set_value, "Item", item, "default_production_center", before)
		order = self._ordered(COLA)
		sent = kitchen.send_to_kitchen(order)
		order.reload()
		orders.set_item_notes(order, item_idx=1, notes="No ice")

		notes = [
			row.notes
			for ticket in sent["kots_created"]
			for row in frappe.get_all("KOT Item", filters={"parent": ticket["kot_name"]}, fields=["notes"])
		]
		self.assertTrue(notes)
		for note in notes:
			self.assertIn("No ice", note)
			self.assertIn("Burger meal", note)

	def test_the_meal_comes_back_whole(self):
		order = self._paid(JUICE)
		offered = returns.returnable(order)["items"]

		self.assertEqual(len(offered), 1)
		self.assertEqual(offered[0]["item"], MEAL)
		self.assertAlmostEqual(offered[0]["amount"], MEAL_PRICE + UPGRADE, places=2)

		# Back on the shelf, said outright: a meal is waste unless the cashier says not (`D-315`).
		result = returns.create_return(
			order, items=[{"row": offered[0]["row"], "qty": 1, "wasted": 0}], reason_code="goods_returned"
		)
		back = self._moved(result["credit_note"])
		self.assertEqual(back[JUICE], 1)
		self.assertEqual(back["RPOS-TEST-PATTY"], 0.15)

	def test_the_till_is_sent_the_choices_as_a_popup(self):
		items, _groups = session._catalog(frappe.get_doc("POS Profile", self.profile), [])
		meal = next(item for item in items if item.item_code == MEAL)
		self.assertEqual(meal.modifier_groups, [combos.group_name(MEAL, DRINK)])

		drink = combos.groups_for(MEAL, TEST_PRICE_LIST)[0]
		self.assertEqual(drink["is_required"], 1)
		prices = {
			option.title: (option.price_effect, flt(option.price_amount)) for option in drink["options"]
		}
		self.assertEqual(prices, {COLA: ("none", 0.0), JUICE: ("add", UPGRADE)})


class AComboItemTakesItsOwnAddOns(ComboTestBase):
	"""`D-289` — extra cheese on the meal's burger, as on a burger alone."""

	def setUp(self):
		super().setUp()
		from restaurant_pos.tests import test_addons

		self.addons = test_addons
		test_addons._group()
		frappe.db.delete("Modifier Group Assignment", {"parent": ITEM, "parenttype": "Item"})
		frappe.get_doc(
			{
				"doctype": "Modifier Group Assignment",
				"parent": ITEM,
				"parenttype": "Item",
				"parentfield": "pos_modifier_groups",
				"modifier_group": test_addons.GROUP,
			}
		).db_insert()
		self.addCleanup(frappe.db.delete, "Modifier Group Assignment", {"parent": ITEM, "parenttype": "Item"})

	def _ordered_with(self, *extras: str, qty: float = 1):
		part = combos.part_group_name(MEAL, ITEM, self.addons.GROUP)
		order = self._order()
		orders.add_item(
			order,
			item=MEAL,
			qty=qty,
			modifiers=[
				{"group": combos.group_name(MEAL, DRINK), "option": COLA},
				*({"group": part, "option": extra} for extra in extras),
			],
		)
		order.reload()
		return order

	def test_the_till_asks_the_burger_s_groups_inside_the_meal(self):
		self.assertIn(combos.part_group_name(MEAL, ITEM, self.addons.GROUP), combos.slot_names(MEAL))
		part = combos.part_groups(MEAL)[0]
		self.assertIsNone(part["when"], "the burger always comes, so its groups always show")

	def test_extra_cheese_adds_its_price_and_is_sold_as_its_own_line(self):
		order = self._ordered_with("Extra cheese", qty=2)
		self.assertEqual(flt(order.items[0].amount), 2 * (MEAL_PRICE + self.addons.EXTRA))

		self._pay(order)
		order.reload()
		lines = self._lines(order.sales_invoice)
		cheese = next(line for line in lines if line.item_code == self.addons.CHEESE)
		self.assertEqual((flt(cheese.qty), flt(cheese.rate)), (2, self.addons.EXTRA))
		self.assertEqual(cheese.rpos_combo, MEAL)
		self.assertAlmostEqual(sum(flt(line.amount) for line in lines), flt(order.items[0].amount), places=2)

		moved = self._moved(order.sales_invoice)
		self.assertEqual(moved[self.addons.CHEESE], -4, "two from the recipes, two extra")

	def test_an_extra_with_no_stock_stays_on_its_own_item_s_line(self):
		"""«Large» on the tea is the tea's money — not shared into the burger (owner's sale)."""
		self.addons._group(
			{"title": "Double", "title_ar": "دبل", "price_effect": "add", "price_amount": 4, "is_active": 1}
		)
		order = self._ordered_with("Double")
		self._pay(order)
		order.reload()

		lines = {line.item_code: flt(line.rate) for line in self._lines(order.sales_invoice)}
		whole = TEST_ITEM_RATE + COLA_PRICE
		self.assertAlmostEqual(lines[COLA], flt(MEAL_PRICE * COLA_PRICE / whole, 2), places=2)
		self.assertAlmostEqual(lines[ITEM], MEAL_PRICE - lines[COLA] + 4, places=2)

	def test_no_bun_on_the_meal_s_burger_keeps_the_bun(self):
		order = self._ordered_with("No bun")
		self._pay(order)
		order.reload()

		self.assertNotIn(self.addons.BUN, self._moved(order.sales_invoice))


class AChoiceSaysHowManyToPick(ComboTestBase):
	"""`D-290` — Square's number of selections, Toast's minimum and maximum."""

	def _drinks(self, low: int, high: int):
		_choice(DRINK, low, high)
		return [{"group": combos.group_name(MEAL, DRINK), "option": drink} for drink in (COLA, JUICE)]

	def test_an_optional_choice_may_be_left_empty(self):
		self._drinks(0, 1)
		order = self._order()
		orders.add_item(order, item=MEAL, qty=1, modifiers=[])
		order.reload()

		self.assertEqual([part["item"] for part in combos.parts(order.items[0])], [ITEM])
		self.assertEqual(combos.groups_for(MEAL, TEST_PRICE_LIST)[0]["is_required"], 0)

	def test_a_choice_of_two_takes_both_and_prices_the_upgrade(self):
		both = self._drinks(1, 2)
		order = self._order()
		orders.add_item(order, item=MEAL, qty=1, modifiers=both)
		order.reload()

		self.assertEqual({part["item"] for part in combos.parts(order.items[0])}, {ITEM, COLA, JUICE})
		self.assertEqual(flt(order.items[0].amount), MEAL_PRICE + UPGRADE)
		self.assertEqual(combos.groups_for(MEAL, TEST_PRICE_LIST)[0]["selection_type"], "multiple")

	def test_more_than_the_choice_allows_is_refused(self):
		both = self._drinks(1, 1)
		order = self._order()
		with self.assertRaises(frappe.ValidationError):
			orders.add_item(order, item=MEAL, qty=1, modifiers=both)

	def test_a_minimum_above_the_maximum_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "POS Combo Choice",
					"title_ar": "خيار خاطئ",
					"title": "Wrong",
					"min_selections": 3,
					"max_selections": 1,
				}
			).insert(ignore_permissions=True)


class AChoiceOffersAWholeGroup(ComboTestBase):
	"""`D-294` — «any drink»: Square's category option, Fitec's component groups."""

	GROUP = "RPOS Test Drinks"

	def setUp(self):
		super().setUp()
		if not frappe.db.exists("Item Group", self.GROUP):
			frappe.get_doc(
				{
					"doctype": "Item Group",
					"item_group_name": self.GROUP,
					"parent_item_group": "All Item Groups",
				}
			).insert(ignore_permissions=True)
		for drink in (COLA, JUICE):
			before = frappe.db.get_value("Item", drink, "item_group")
			frappe.db.set_value("Item", drink, "item_group", self.GROUP)
			self.addCleanup(frappe.db.set_value, "Item", drink, "item_group", before)
		frappe.db.set_value("POS Combo Choice", DRINK, "item_group", self.GROUP)
		self.addCleanup(frappe.db.set_value, "POS Combo Choice", DRINK, "item_group", None)

	def _any_drink(self, *extra: dict) -> None:
		meal = frappe.get_doc("Item", MEAL)
		meal.rpos_combo_pricing = "fixed"
		meal.set("rpos_combo_items", [{"slot": "", "item": ITEM, "qty": 1}, {"slot": DRINK}, *extra])
		meal.save(ignore_permissions=True)

	def test_one_row_offers_every_item_of_the_group_inside_the_price(self):
		self._any_drink()

		offered = {
			option.title: flt(option.price_amount)
			for option in combos.groups_for(MEAL, TEST_PRICE_LIST)[0]["options"]
		}
		self.assertEqual(offered, {COLA: 0.0, JUICE: 0.0})
		self.assertEqual(flt(self._ordered(JUICE).items[0].amount), MEAL_PRICE)

	def test_a_row_for_one_of_them_prices_it_differently(self):
		self._any_drink(
			{"slot": DRINK, "item": JUICE, "price_source": "amount", "price": UPGRADE, "adds_to_price": 1}
		)

		offered = {
			option.title: flt(option.price_amount)
			for option in combos.groups_for(MEAL, TEST_PRICE_LIST)[0]["options"]
		}
		self.assertEqual(offered, {JUICE: UPGRADE, COLA: 0.0})
		self.assertEqual(flt(self._ordered(JUICE).items[0].amount), MEAL_PRICE + UPGRADE)

	def test_a_row_without_an_item_needs_a_choice_with_a_group(self):
		frappe.db.set_value("POS Combo Choice", DRINK, "item_group", None)
		with self.assertRaises(frappe.ValidationError):
			self._any_drink()


class TheComboInItemSales(ComboTestBase):
	"""`D-286` — «how many meals, and how many burgers of them»."""

	def _rows(self, **flags) -> dict:
		from frappe.utils import today

		from restaurant_pos.restaurant_pos.report.item_sales import item_sales

		# A sale's cost is known once its day is posted (`D-314`).
		posting.post_branch(BRANCH)
		_columns, rows, *_rest = item_sales.execute(
			frappe._dict(from_date=today(), to_date=today(), pos_profile=self.profile, show_cost=1, **flags)
		)
		return {row["item_code"]: row for row in rows if row.get("item_code")}

	def test_the_items_say_how_many_went_out_in_combos(self):
		before = self._rows().get(COLA, {"qty": 0.0, "combo_qty": 0.0})
		self._paid(COLA, qty=2)
		after = self._rows()[COLA]

		self.assertEqual(after["qty"] - before["qty"], 2)
		self.assertEqual(after["combo_qty"] - before["combo_qty"], 2)
		self.assertNotIn(MEAL, self._rows())

	def test_combos_as_meals_counts_the_meals_with_their_money_and_cost(self):
		before = self._rows(combos_as_meals=1).get(MEAL, {"qty": 0.0, "amount": 0.0, "cost": 0.0})
		order = self._paid(COLA, qty=2)
		after = self._rows(combos_as_meals=1)[MEAL]

		net = sum(
			flt(line.net_amount)
			for line in frappe.get_all(
				SALE_ITEM, filters={"parent": order.sales_invoice}, fields=["net_amount"]
			)
		)
		self.assertEqual(after["qty"] - before["qty"], 2)
		self.assertAlmostEqual(after["amount"] - before["amount"], net, places=2)
		self.assertAlmostEqual(after["cost"] - before["cost"], 2 * (COST_OF_ONE + 1.00), places=2)

	def test_a_returned_meal_is_counted_back_as_a_meal(self):
		order = self._paid(COLA)
		before = self._rows(combos_as_meals=1)[MEAL]
		row = returns.returnable(order)["items"][0]["row"]
		returns.create_return(
			order, items=[{"row": row, "qty": 1, "wasted": 0}], reason_code="goods_returned"
		)
		after = self._rows(combos_as_meals=1)[MEAL]

		self.assertEqual(after["returned_qty"] - before["returned_qty"], 1)
		self.assertAlmostEqual(after["cost"] - before["cost"], -(COST_OF_ONE + 1.00), places=2)


class ASumPricedCombo(ComboTestBase):
	def setUp(self):
		super().setUp()
		self._meal("sum")

	def test_the_meal_costs_its_items_added_up(self):
		self.assertEqual(flt(self._ordered(COLA).items[0].amount), TEST_ITEM_RATE + COLA_PRICE)
		order = self._paid(JUICE)
		self.assertEqual(
			{line.item_code: flt(line.rate) for line in self._lines(order.sales_invoice)},
			{ITEM: TEST_ITEM_RATE, JUICE: JUICE_PRICE},
		)


class TheComboIsCheckedWhenSaved(ComboTestBase):
	def test_a_choice_must_be_made(self):
		order = self._order()
		with self.assertRaises(frappe.ValidationError):
			orders.add_item(order, item=MEAL, qty=1, modifiers=[])

	def test_an_item_not_offered_under_the_choice_is_refused(self):
		order = self._order()
		with self.assertRaises(frappe.ValidationError):
			orders.add_item(
				order, item=MEAL, qty=1, modifiers=[{"group": combos.group_name(MEAL, DRINK), "option": ITEM}]
			)

	def test_a_combo_is_not_kept_in_stock(self):
		meal = frappe.get_doc("Item", MEAL)
		meal.is_stock_item = 1
		with self.assertRaises(frappe.ValidationError):
			meal.save(ignore_permissions=True)

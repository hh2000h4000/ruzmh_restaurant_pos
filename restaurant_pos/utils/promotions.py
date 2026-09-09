# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Which promotion applies to a bill, and what it takes off (`FR-11`, `D-163`).

**A promotion is not a discount** (`BR-032`). A discount is a person deciding to
take something off, inside a ceiling their permission sets. A promotion is a
rule the restaurant configured in advance, and nobody at the till decides it.

## The three rules that decide, and why they are these

Researched before they were written, because getting this wrong is expensive in
a way a cashier cannot see: two promotions that quietly compound produce a
number nobody sized, discovered at the till with the customer standing there.

1. **A single item is never touched by two promotions.** The constraint every
   serious till states outright. Without it, "20% off grills" and "20% off
   Tuesdays" make 36% off a kebab and no one chose that.
2. **Priority first.** A number on the promotion; higher goes first. It is what
   a manager reaches for when two offers overlap on purpose.
3. **On a tie, the greater discount wins** — the customer's side of it, and the
   user's own choice. An unset priority is therefore *safe* rather than
   arbitrary: the shop never accidentally gives less than it advertised.

**And that resolves the contradiction in our own documents.** `BR-034` said
promotions stack unless exclusive; `BR-035` said the best one wins. Both hold,
because they were answering different questions: two promotions may apply to one
**bill** — on different items — and no single item takes two. `is_exclusive`
keeps its own meaning: this promotion does not combine with a *manual* discount.

Refs: FR-11.1, FR-11.2, BR-032, BR-033, BR-034, BR-035, D-163
"""

from datetime import timedelta

import frappe
from frappe.utils import flt, get_datetime, getdate, nowtime

#: Columns of `Restaurant Promotion` the engine reads. Named so a schema change
#: that drops one fails here rather than silently evaluating to nothing.
FIELDS = (
	"name",
	"title",
	"title_ar",
	"priority",
	"is_auto_apply",
	"is_exclusive",
	"valid_from",
	"valid_to",
	"time_from",
	"time_to",
	"promotion_type",
	"discount_value",
	"min_order_amount",
	"buy_qty",
	"get_qty",
	"free_item",
	"free_item_group",
	"free_qty",
	"apply_to",
	"item_scope",
)

#: The weekday checkboxes, in `datetime.weekday()` order.
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

#: What the engine takes off a bill on its own.
#:
#: **All four, and none of them needs a screen** (`D-173`, `D-175`).
#:
#: The last two were shut for a while on the reasoning that a reward has to be
#: *given*, and giving needs somebody to choose. That was wrong, and the way it
#: was wrong is worth keeping: **the guest chooses by ordering.** The cashier
#: rings the drink the guest asked for, and the offer takes its price off a line
#: already on the ticket — which is what every till of this kind does.
#:
#: What none of them does is **add** a line. A promotion that put a drink on a
#: bill nobody ordered would charge nothing for it and tell the kitchen to make
#: it. If the reward is not on the bill, the offer is simply not on offer.
SUPPORTED = ("percentage", "fixed_amount", "buy_x_get_y", "free_item")


def active_for(order, total: float | None = None) -> list[frappe._dict]:
	"""Every promotion whose conditions this bill meets, right now.

	``total`` is what the minimum spend is measured against. Passed in rather
	than read off the order, because the caller inside `totals.calculate` is
	**part way through working that figure out** — reading `order.total_amount`
	there gets the previous save's number, and a bill that had just crossed the
	minimum did not qualify. Defaults to the stored total for a caller that is
	only asking what is on offer.

	Ordered the way they compete: priority first, then the bigger discount. The
	caller takes the head of the list, which is why the ordering is here and not
	spread over the callers.
	"""
	moment = get_datetime()
	candidates = frappe.get_all(
		"Restaurant Promotion",
		filters={"is_active": 1, "promotion_type": ("in", SUPPORTED)},
		fields=list(FIELDS),
	)

	measured = flt(order.total_amount) if total is None else flt(total)
	eligible = [row for row in candidates if _applies(row, order, measured, moment)]
	for row in eligible:
		row.benefit = benefit_of(row, order)

	# Highest priority first; on a tie the customer's better deal. Both
	# descending, so one `sort` says the whole rule.
	eligible.sort(key=lambda row: (flt(row.priority), flt(row.benefit)), reverse=True)
	# **Worth nothing means not on offer.** `free_item` used to be exempt here,
	# because its benefit was a notional list price rather than money off this
	# bill. It is priced from the bill now (`D-175`), so the honest test covers
	# every reward: an offer whose free drink is not on the ticket takes nothing
	# off, and showing it to a cashier would be offering what cannot be given.
	return [row for row in eligible if flt(row.benefit) > 0]


def best_for(order, total: float | None = None) -> frappe._dict | None:
	"""The one promotion that applies to this bill, or nothing.

	One, because a second would have to touch an item the first already did —
	and that is the rule this module exists to hold (rule 1 above). Splitting a
	bill's items between two promotions is a real thing to want and is not this;
	it needs per-line application, and is not built.

	**A cashier's own choice outranks the ranking** (`D-165`). Priority and the
	better-deal tiebreak decide between promotions when *nobody* has decided —
	that is what makes an unset priority safe rather than arbitrary. Here
	somebody has, and an automatic pick that overrode them would make
	`is_auto_apply = 0` mean nothing at all: the offer would be listed, chosen,
	and then quietly replaced.

	The choice is still held to the same conditions as any other. A promotion
	whose hours have passed, or that covers nothing on this bill, does not apply
	because it was picked — it just stops being on offer.
	"""
	on_offer = active_for(order, total)

	if order.get("chosen_promotion"):
		picked = [row for row in on_offer if row.name == order.chosen_promotion]
		if picked:
			return picked[0]

	auto = [row for row in on_offer if row.is_auto_apply]
	return auto[0] if auto else None


def benefit_of(promotion, order) -> float:
	"""What this promotion would take off, in riyals.

	The number the tie is broken on, so it is worked out the same way for every
	type — a percentage and a fixed amount have to be comparable or "the better
	deal" means nothing.
	"""
	base = _eligible_amount(promotion, order)

	if promotion.promotion_type == "percentage":
		return flt(base * flt(promotion.discount_value) / 100.0, 2)

	if promotion.promotion_type == "fixed_amount":
		# Never more than the bill: a 50 riyal voucher on a 30 riyal order takes
		# 30, not 50, and certainly does not hand money back.
		return flt(min(flt(promotion.discount_value), base), 2)

	if promotion.promotion_type == "buy_x_get_y":
		return flt(sum(_free_units(promotion, order).values()), 2)

	if promotion.promotion_type == "free_item":
		return flt(sum(_free_reward_units(promotion, order).values()), 2)

	return 0.0


def _free_units(promotion, order) -> dict[int, float]:
	"""Which lines lose how much to a *buy X get Y* offer (`D-173`).

	**The cheapest units are the free ones**, which is what every till of this
	kind does and the only reading a guest will accept: buy two get one on a
	kebab and a soup hands back the soup, not the kebab.

	**And the offer repeats.** Buy two get one on six units gives two free, not
	one — a rule that fired once and then stopped would have the shop advertising
	an offer it silently withdraws mid-basket.

	**Counted across every line the offer covers, not per dish.** *Buy 2 get 1 on
	drinks* means three drinks, and a guest who took two juices and a water has
	bought three drinks. Counting per line would make the same basket qualify or
	not depending on how the cashier happened to key it.

	Returns what comes off each line, so the figure and the marks on the screen
	are the same arithmetic rather than two that can drift (§5.5).
	"""
	buy, get = max(0, int(promotion.buy_qty or 0)), max(0, int(promotion.get_qty or 0))
	if not buy or not get:
		return {}

	units = _units_of(_covered_lines(promotion, order))
	return _cheapest(units, (len(units) // (buy + get)) * get)


def _units_of(lines: list) -> list[tuple[float, int]]:
	"""One entry per unit, priced, with the line it came from.

	**Offers of this kind count units, not lines**: a line of three burgers is
	three chances at a threshold, and a guest who took two juices and a water
	took three drinks however the cashier keyed them.
	"""
	units: list[tuple[float, int]] = []
	for row in lines:
		count = int(flt(row.qty))
		if count <= 0:
			continue

		each = flt(row.amount) / flt(row.qty)
		units.extend((each, row.idx) for _ in range(count))

	return units


def _cheapest(units: list[tuple[float, int]], count: int) -> dict[int, float]:
	"""What comes off each line when ``count`` units are given away.

	**The cheapest are the free ones**, which is what every till of this kind
	does and the only reading a guest accepts: buy two get one on a kebab and a
	soup hands back the soup, not the kebab.

	One function for both rewards, because they are one question — *which units
	are free and what do they cost* — and two copies of it is how a bill comes to
	be discounted on one set and to say it was discounted on another (§5.5).
	"""
	if count <= 0:
		return {}

	shares: dict[int, float] = {}
	for each, idx in sorted(units)[:count]:
		shares[idx] = flt(shares.get(idx, 0.0) + each, 2)

	return shares


def _free_reward_units(promotion, order) -> dict[int, float]:
	"""Which lines a *free item* reward comes off (`D-175`).

	**The guest chooses by ordering it, so no screen is needed** — and that is a
	correction to `D-163`, which shut this reward on the reasoning that *any
	drink with a kabsa* leaves somebody to pick the drink. Somebody does: the
	guest, at the counter, and the cashier rings it up. The offer then takes its
	price off, which is what the research says every till of this kind does — it
	discounts a line on the ticket rather than inventing one.

	**And it never adds a line.** A promotion that put a drink on a bill nobody
	ordered would be worse than none: the guest is charged nothing for it and the
	kitchen is told to make it. If the reward is not on the bill the offer simply
	is not on offer, and `active_for` drops it for being worth nothing.

	`free_qty` units come free, cheapest first — the same rule as its neighbour,
	from the same function.
	"""
	lines = [row for row in (order.items or []) if row.status != "void"]

	if promotion.free_item:
		lines = [row for row in lines if row.item == promotion.free_item]
	elif promotion.free_item_group:
		groups = _groups_under([promotion.free_item_group])
		lines = [row for row in lines if _group_of(row.item) in groups]
	else:
		return {}

	return _cheapest(_units_of(lines), max(1, int(promotion.free_qty or 1)))


def blocks_a_discount(order) -> str:
	"""The title of an exclusive offer standing on this bill, or "" (`D-169`).

	**`is_exclusive` was a checkbox nobody read.** It sat on the record, went out
	to the client, and no line of code anywhere acted on it: a manager could tick
	*does not combine with a manual discount*, and the till would take the offer
	and the discount together — the shop giving away twice what it agreed to,
	with the record insisting otherwise. The same silence as a promotion that
	saves and does nothing (`D-074`), pointed the other way.

	It refuses the **discount**, not the promotion. The offer is a rule the shop
	published and a guest may have come in for; the discount is being typed now
	by somebody who can be told why. A shop that wants the discount anyway turns
	the flag off on the promotion, which is a manager's decision in the desk —
	where the rule was made.

	Returns the title so the caller can name it. A refusal that will not say
	*which* offer is the report nobody can act on.
	"""
	chosen = best_for(order)
	if not chosen or not chosen.is_exclusive:
		return ""

	return chosen.title_ar or chosen.title or chosen.name


def per_line(order) -> dict[int, float]:
	"""Which lines the promotion touched, and what came off each (`D-166`).

	**A total that says "-13.00" does not say which dish it came off.** On a bill
	where the offer covers three items out of seven, the cashier cannot answer
	the guest pointing at the fourth — and that is the question the guest asks.
	Toast puts the discount as a line beneath the item it discounted; Foodics
	writes the offer's name under the dish; the till the user works on marks the
	covered lines and leaves the rest bare. All three answer *which*, which the
	bill's own total never can.

	**The parts add up to the whole, exactly.** Each line takes its share of the
	promotion in proportion to what it contributed, and the last covered line
	absorbs whatever rounding left over — because a receipt whose lines do not
	sum to its total is read as a mistake by the one person who cannot check it
	(`D-162`).

	Keyed by ``idx``, and empty when no promotion applied.
	"""
	if not order.get("promotion") or not flt(order.get("promotion_amount")):
		return {}

	promotion = frappe.db.get_value(
		"Restaurant Promotion",
		order.promotion,
		[
			"name",
			"item_scope",
			"promotion_type",
			"buy_qty",
			"get_qty",
			"free_item",
			"free_item_group",
			"free_qty",
		],
		as_dict=True,
	)
	if not promotion:
		return {}

	# **A reward that frees whole units does not spread across the bill.**
	# Specific units are free — the cheapest ones — so the marks are exactly
	# those, worked out by the same function that priced them.
	if promotion.promotion_type == "buy_x_get_y":
		return _free_units(promotion, order)

	if promotion.promotion_type == "free_item":
		return _free_reward_units(promotion, order)

	covered = _covered_lines(promotion, order)
	base = flt(sum(flt(row.amount) for row in covered), 2)
	if not covered or base <= 0:
		return {}

	total = flt(order.promotion_amount)
	shares: dict[int, float] = {}
	running = 0.0

	for row in covered[:-1]:
		share = flt(total * flt(row.amount) / base, 2)
		shares[row.idx] = share
		running = flt(running + share, 2)

	# The last one takes the remainder rather than its own rounded share, so the
	# lines sum to the figure on the bill and not to a cent beside it.
	shares[covered[-1].idx] = flt(total - running, 2)
	return shares


def offers_for(order) -> list[dict]:
	"""What this bill qualifies for, for a cashier to choose from (`D-165`).

	**A promotion with `is_auto_apply` off is offered rather than taken** — and
	until now there was nothing to offer it *on*. It could be configured, saved
	and listed as active, and no screen showed it and no endpoint applied it:
	configuration that looks complete and does nothing, which is the defect this
	module refuses `buy_x_get_y` at the door for (`D-074`). It shipped with the
	same hole one field over.

	The automatic ones are here too, and deliberately: where two of them apply,
	the engine picks by priority and the cashier may still have a reason to want
	the other. What is *not* here is anything the bill does not qualify for —
	choosing does not exempt a promotion from its own conditions.
	"""
	return [
		{
			"name": row.name,
			"title": row.title,
			"title_ar": row.title_ar,
			"benefit": flt(row.benefit),
			"is_auto_apply": 1 if row.is_auto_apply else 0,
			"is_chosen": 1 if row.name == order.get("chosen_promotion") else 0,
		}
		for row in active_for(order)
	]


def on_the_bill(order) -> dict:
	"""What the bill has to say about the promotion that was applied (`D-163`).

	**The engine takes money off without anybody at the till agreeing to it**, so
	every screen showing a total has to be able to name the rule that did it. A
	figure that drops by ten riyals with nothing saying why is the report a
	manager cannot act on, and the cashier standing in front of the guest cannot
	answer either (`D-074`).

	One shape, built here, spread into each payload — because the till, the
	payment screen and the guest's screen are asking the same question, and three
	copies of it is how two of them end up saying something different (§5.5).

	The title travels with the bill rather than being looked up client-side
	against the cached promotion list: a promotion created after this terminal
	signed in is not in that cache, and the row would render with an empty name.
	"""
	titles = (
		frappe.get_cached_value("Restaurant Promotion", order.promotion, ["title", "title_ar"])
		if order.promotion
		else None
	)
	return {
		"promotion_amount": flt(order.promotion_amount),
		"promotion_title": (titles[0] if titles else "") or "",
		"promotion_title_ar": (titles[1] if titles else "") or "",
	}


# --------------------------------------------------------------------------- #
# Whether one promotion applies
# --------------------------------------------------------------------------- #


def _applies(promotion, order, total: float, moment) -> bool:
	"""Every condition, in the order that rejects most cheaply."""
	return (
		_within_dates(promotion, moment)
		and _on_this_weekday(promotion, moment)
		and _within_hours(promotion)
		and _meets_minimum(promotion, total)
		and _in_scope(promotion, order)
		and _eligible_amount(promotion, order) > 0
	)


def _within_dates(promotion, moment) -> bool:
	today = getdate(moment)
	if promotion.valid_from and today < getdate(promotion.valid_from):
		return False
	return not (promotion.valid_to and today > getdate(promotion.valid_to))


def _on_this_weekday(promotion, moment) -> bool:
	"""No day ticked means every day — an unconfigured promotion is not a dead one."""
	ticked = [day for day in WEEKDAYS if promotion.get(day)]
	return not ticked or WEEKDAYS[getdate(moment).weekday()] in ticked


def _within_hours(promotion) -> bool:
	"""Happy hour, including one that runs past midnight.

	Three ways to get this wrong, and this function had two of them.

	**An unset window does not arrive as `None`.** Frappe stamps every `Time`
	field with the current clock on insert (`create_new.py:149`), so a promotion
	saved without hours holds the same instant in both fields — and testing
	"unset" by truthiness passes that straight through as a window one moment
	wide. Every such promotion is then outside its own hours a second later:
	saved, listed as active, never applying, and nothing anywhere saying why
	(`D-074`). That is what the flaky test was reporting; it passed only when the
	whole run happened to land inside the same second. The controller now clears
	the stamp on save (`drop_the_framework_stamp`), and this holds the same line
	for every row already in the database.

	**And these are times, not strings.** Compared as text, a nine o'clock start
	arriving as `9:30:00` sorts *after* `16:00:00`, because `"9" > "1"` — so
	every promotion starting before ten in the morning would have been wrong.

	The third is the one that was already right: `22:00` to `02:00` is an
	ordinary late offer, and a window that wraps past midnight has to be read as
	one rather than as an empty range.
	"""
	start, end = _seconds(promotion.time_from), _seconds(promotion.time_to)

	# No window, or one too short to be a happy hour, means all day.
	if start is None or end is None or abs(end - start) < 60:
		return True

	now = _seconds(nowtime()) or 0
	return start <= now <= end if start < end else now >= start or now <= end


def _seconds(value) -> int | None:
	"""A clock value as seconds since midnight, whatever shape it arrived in.

	Frappe hands a `Time` column back as a `timedelta` from the database and as a
	string from a document, and the two do not compare with each other. Seconds
	compare the same way whichever arrived.
	"""
	if value in (None, ""):
		return None

	# What the database hands back, and the only shape that needs its own
	# branch: going through `str()` would work but round-trips the value through
	# text to get a number that is already there.
	if isinstance(value, timedelta):
		return int(value.total_seconds())

	parts = str(value).split(":")
	if len(parts) < 2:
		return None

	hours, minutes = int(parts[0]), int(parts[1])
	whole = int(float(parts[2])) if len(parts) > 2 else 0
	return hours * 3600 + minutes * 60 + whole


def _meets_minimum(promotion, total: float) -> bool:
	minimum = flt(promotion.min_order_amount)
	return not minimum or flt(total) >= minimum


def _in_scope(promotion, order) -> bool:
	"""Branch, section and order type (`BR-033`).

	An empty list means "everywhere", the same convention the order types use:
	a promotion nobody has scoped is on for the whole shop, not off everywhere.
	"""
	scopes = {
		"by_order_type": ("Promotion Order Type", "order_type", order.order_type),
		"by_branch": ("Promotion Branch", "branch", order.branch),
		"by_section": ("Promotion Section", "section", order.section),
	}
	if promotion.apply_to not in scopes:
		return True

	doctype, column, value = scopes[promotion.apply_to]
	allowed = frappe.get_all(doctype, filters={"parent": promotion.name}, pluck=column)
	return not allowed or value in allowed


def _eligible_amount(promotion, order) -> float:
	"""What of this bill the promotion is allowed to discount (`FR-11.1`)."""
	return flt(sum(flt(row.amount) for row in _covered_lines(promotion, order)), 2)


def _covered_lines(promotion, order) -> list:
	"""The lines a promotion reaches — the one place that decides (§5.5).

	Both the amount it takes off and the marks the screen draws are answers to
	this same question, and asking it twice is how a bill comes to be discounted
	on one set of lines and to say so on another.

	Voided lines are not part of it — they are not part of what is owed either.
	"""
	lines = [row for row in (order.items or []) if row.status != "void"]

	if promotion.item_scope == "specific_items":
		wanted = set(frappe.get_all("Promotion Item", filters={"parent": promotion.name}, pluck="item"))
		return [row for row in lines if row.item in wanted]

	if promotion.item_scope == "specific_groups":
		groups = _groups_under(
			frappe.get_all("Promotion Item Group", filters={"parent": promotion.name}, pluck="item_group")
		)
		return [row for row in lines if _group_of(row.item) in groups]

	return lines


def _groups_under(chosen: list[str]) -> set[str]:
	"""The chosen item groups **and everything beneath them** (`D-169`).

	`Item Group` is a tree, and an item hangs off a leaf of it. A manager who
	picks *Drinks* means every drink — the hot ones and the cold ones — and a
	comparison against the item's own group alone would match none of them,
	because no item is ever *in* `Drinks`; they are in its children.

	**And it fails in the direction that costs money quietly.** The promotion
	saves, reads as active, covers nothing, and the shop finds out when a guest
	who was promised an offer does not get it. Nothing about the record says why
	(`D-074`).

	Frappe keeps the tree as a nested set, so each group's descendants are one
	range query rather than a walk.
	"""
	from frappe.utils.nestedset import get_descendants_of

	under = set(chosen)
	for group in chosen:
		under.update(get_descendants_of("Item Group", group, ignore_permissions=True))

	return under


def _group_of(item: str) -> str | None:
	return frappe.get_cached_value("Item", item, "item_group") if item else None

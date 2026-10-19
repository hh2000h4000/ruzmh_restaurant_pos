# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Whitelisted order endpoints.

Thin by design (``02_backend_rules.md``): parse, authorise, delegate to
``utils.order``, return JSON. Every function that changes data is replay-safe
on ``queue_id`` (``09`` §8).

Refs: 07_API_Design.md §3, FR-2.1..FR-2.8
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, get_datetime, nowdate

from restaurant_pos.utils import customer as customer_service
from restaurant_pos.utils import idempotency, kitchen, promotions
from restaurant_pos.utils import order as service
from restaurant_pos.utils.deadlock import retried
from restaurant_pos.utils.permissions import get_pos_permission_set, validate_branch_access
from restaurant_pos.utils.sale_doc import SALE


def _load(order_name: str):
	order = frappe.get_doc("Restaurant Order", order_name)
	validate_branch_access(order.branch)
	return order


def _summary(order) -> dict:
	return {
		"order_name": order.name,
		"status": order.status,
		"subtotal": order.subtotal,
		"discount_amount": order.discount_amount,
		**promotions.on_the_bill(order),
		# What the points paid, so a paid bill reads them as points and not as a
		# discount (`D-189`). The balance is not here: every order fetch would
		# pay for a ledger sum the till screen never shows.
		"loyalty_points": cint(order.get("loyalty_points")),
		"loyalty_amount": flt(order.get("loyalty_amount")),
		"tax_amount": order.tax_amount,
		"total_amount": order.total_amount,
		"item_count": len([row for row in order.items if row.status != "void"]),
	}


@frappe.whitelist()
@retried
def create_order(
	order_type: str,
	pos_profile: str,
	table: str | None = None,
	customer: str | None = None,
	delivery_address: str | None = None,
	cover_count: int | None = None,
	waiter: str | None = None,
	order_type_data: dict | str | None = None,
	notes: str | None = None,
	call_name: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Open an order (FR-2.1)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	existing = (
		frappe.db.get_value("Restaurant Order", {"offline_queue_id": queue_id}, "name") if queue_id else None
	)
	if existing:
		return dict(_summary(frappe.get_doc("Restaurant Order", existing)), already_processed=True)

	order = service.create_order(
		order_type=order_type,
		pos_profile=pos_profile,
		table=table,
		customer=customer,
		delivery_address=delivery_address,
		cover_count=cover_count,
		waiter=waiter,
		order_type_data=frappe.parse_json(order_type_data)
		if isinstance(order_type_data, str)
		else order_type_data,
		notes=notes,
		call_name=call_name,
		offline_queue_id=queue_id,
	)

	result = _summary(order)
	idempotency.remember(
		queue_id,
		"create_order",
		result,
		reference_doctype="Restaurant Order",
		reference_name=order.name,
	)
	return result


@frappe.whitelist()
@retried
def add_item(
	order_name: str,
	item: str,
	qty: float = 1,
	modifiers: list | str | None = None,
	notes: str | None = None,
	course: int | None = None,
	rate: float | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Add a line (FR-2.2).

	``rate`` is ignored unless the caller holds ``can_change_item_price``; the
	price otherwise comes from the price list (``DECISIONS.md`` D-020).
	"""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	row = service.add_item(
		order,
		item=item,
		qty=qty,
		modifiers=frappe.parse_json(modifiers) if isinstance(modifiers, str) else modifiers,
		notes=notes,
		course=course,
		rate=rate,
		join=True,
	)

	result = dict(_summary(order), row_idx=row.idx, rate=row.rate, amount=row.amount)
	idempotency.remember(
		queue_id, "add_item", result, reference_doctype="Restaurant Order", reference_name=order.name
	)
	return result


@frappe.whitelist()
@retried
def set_item_qty(
	order_name: str,
	item_idx: int,
	qty: float,
	queue_id: str | None = None,
) -> dict:
	"""Change how many of a line, before it goes to the kitchen (FR-2.2)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	outcome = service.set_item_qty(order, item_idx=item_idx, qty=qty)

	result = dict(_summary(order), **outcome)
	idempotency.remember(
		queue_id, "set_item_qty", result, reference_doctype="Restaurant Order", reference_name=order.name
	)
	return result


@frappe.whitelist()
@retried
def set_item_notes(
	order_name: str,
	item_idx: int,
	notes: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Change one line's note (FR-2.9)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	outcome = service.set_item_notes(order, item_idx=item_idx, notes=notes)

	result = dict(_summary(order), **outcome)
	idempotency.remember(
		queue_id, "set_item_notes", result, reference_doctype="Restaurant Order", reference_name=order.name
	)
	return result


@frappe.whitelist()
@retried
def remove_item(order_name: str, item_idx: int, queue_id: str | None = None) -> dict:
	"""Take a line off before the kitchen sees it (FR-2.5).

	No reason and no permission: until the ticket prints this is composing an
	order, not withdrawing food.
	"""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	outcome = service.remove_item(order, item_idx=item_idx)

	result = dict(_summary(order), **outcome)
	idempotency.remember(
		queue_id, "remove_item", result, reference_doctype="Restaurant Order", reference_name=order.name
	)
	return result


@frappe.whitelist()
@retried
def void_item(
	order_name: str,
	item_idx: int,
	reason: str,
	manager_override_token: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Void a line (FR-2.5)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	outcome = service.void_item(
		order, item_idx=item_idx, reason=reason, override_token=manager_override_token
	)

	result = dict(_summary(order), **outcome)
	idempotency.remember(
		queue_id, "void_item", result, reference_doctype="Restaurant Order", reference_name=order.name
	)
	return result


@frappe.whitelist()
def preview_order_type_change(order_name: str, order_type: str) -> dict:
	"""What the bill would become under another order type (D-038).

	Read-only, so it takes no ``queue_id``: the cashier is being shown a figure,
	not committing to it. A total already read out to a customer does not change
	without them hearing it first.
	"""
	return service.preview_order_type_change(_load(order_name), order_type=order_type)


@frappe.whitelist()
@retried
def change_order_type(
	order_name: str,
	order_type: str,
	table: str | None = None,
	cover_count: int | None = None,
	order_type_data: dict | str | None = None,
	manager_override_token: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Turn an open order into another type, re-pricing it (D-038).

	Only between two types billed to the customer standing there. An app or
	corporate order is owed by somebody else and is refused in the service layer,
	not here — the same rule has to hold for a queued replay.
	"""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	outcome = service.change_order_type(
		order,
		order_type=order_type,
		table=table,
		cover_count=cover_count,
		order_type_data=frappe.parse_json(order_type_data)
		if isinstance(order_type_data, str)
		else order_type_data,
		override_token=manager_override_token,
	)

	result = dict(_summary(order), **outcome)
	idempotency.remember(
		queue_id,
		"change_order_type",
		result,
		reference_doctype="Restaurant Order",
		reference_name=order.name,
	)
	return result


@frappe.whitelist()
@retried
def set_order_table(
	order_name: str,
	table: str,
	cover_count: int | None = None,
	manager_override_token: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Seat an open order at a table, or move it to another one (BR-061).

	Moving an order that already has a table needs ``can_transfer_table`` and is
	audited; seating one that has none is the ordinary flow.
	"""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	outcome = service.seat_order(
		order,
		table=table,
		cover_count=cover_count,
		override_token=manager_override_token,
	)

	result = dict(_summary(order), **outcome)
	idempotency.remember(
		queue_id, "set_order_table", result, reference_doctype="Restaurant Order", reference_name=order.name
	)
	return result


@frappe.whitelist()
@retried
def merge_tables(
	order_name: str,
	tables: list | str,
	manager_override_token: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Join free tables to this bill for one party across several (BR-063, FR-5.4).

	Needs ``can_merge_tables`` and is audited. A table that already carries a
	bill is refused: putting the two bills together is a different act
	(``merge_bills``, BR-067) with its own permission.
	"""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	outcome = service.merge_tables(
		order,
		tables=frappe.parse_json(tables) if isinstance(tables, str) else tables,
		override_token=manager_override_token,
	)

	result = dict(_summary(order), **outcome)
	idempotency.remember(
		queue_id, "merge_tables", result, reference_doctype="Restaurant Order", reference_name=order.name
	)
	return result


@frappe.whitelist()
@retried
def set_order_customer(
	order_name: str,
	customer: str | None = None,
	delivery_address: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Attach a customer to an open order, or change it (FR-2.1 step 4)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	outcome = service.set_customer(order, customer=customer, delivery_address=delivery_address)

	result = dict(_summary(order), **outcome)
	idempotency.remember(
		queue_id,
		"set_order_customer",
		result,
		reference_doctype="Restaurant Order",
		reference_name=order.name,
	)
	return result


@frappe.whitelist()
@retried
def set_call_name(
	order_name: str,
	call_name: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Name the order for calling out — not a Customer (FR-2.11)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	outcome = service.set_call_name(order, call_name=call_name)

	result = dict(_summary(order), **outcome)
	idempotency.remember(
		queue_id, "set_call_name", result, reference_doctype="Restaurant Order", reference_name=order.name
	)
	return result


@frappe.whitelist()
@retried
def set_order_notes(
	order_name: str,
	notes: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Set the note printed on every station's ticket (FR-2.9)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	outcome = service.set_order_notes(order, notes=notes)

	result = dict(_summary(order), **outcome)
	idempotency.remember(
		queue_id, "set_order_notes", result, reference_doctype="Restaurant Order", reference_name=order.name
	)
	return result


@frappe.whitelist()
@retried
def cancel_order(
	order_name: str,
	reason: str,
	manager_override_token: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Cancel an unpaid order (FR-2.8)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	outcome = service.cancel_order(order, reason=reason, override_token=manager_override_token)

	result = dict(_summary(order), **outcome)
	idempotency.remember(
		queue_id, "cancel_order", result, reference_doctype="Restaurant Order", reference_name=order.name
	)
	return result


@frappe.whitelist()
def preview_split(order_name: str, rows: list | str) -> dict:
	"""What the two bills would come to, before anything moves (FR-2.12).

	Read-only, so no `queue_id`: nothing has happened yet.
	"""
	order = _load(order_name)
	return service.preview_split(order, frappe.parse_json(rows) if isinstance(rows, str) else rows)


@frappe.whitelist()
@retried
def split_bill(
	order_name: str,
	rows: list | str,
	cover_count: int | None = None,
	manager_override_token: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Move some lines onto a bill of their own (FR-2.12, BR-067).

	``rows`` is ``[{"idx": 3, "qty": 1}]``; omit ``qty`` to move the whole line.
	"""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	order = _load(order_name)
	outcome = service.split_order(
		order,
		frappe.parse_json(rows) if isinstance(rows, str) else rows,
		cover_count=cover_count,
		override_token=manager_override_token,
	)

	result = dict(_summary(order), **outcome)
	idempotency.remember(
		queue_id, "split_bill", result, reference_doctype="Restaurant Order", reference_name=order.name
	)
	return result


@frappe.whitelist()
@retried
def merge_bills(
	order_name: str,
	into: str,
	manager_override_token: str | None = None,
	queue_id: str | None = None,
) -> dict:
	"""Put one bill onto another and close the empty one (FR-2.12, BR-067)."""
	replay = idempotency.previous_result(queue_id)
	if replay is not None:
		return replay

	source = _load(order_name)
	target = _load(into)
	outcome = service.merge_orders(source, target, override_token=manager_override_token)

	result = dict(_summary(target), **outcome)
	idempotency.remember(
		queue_id, "merge_bills", result, reference_doctype="Restaurant Order", reference_name=target.name
	)
	return result


#: An order the cashier can still act on. Anything else belongs to history.
OPEN_STATUSES = ("draft", "active", "in_kitchen", "pending_payment")

#: A bill that is no longer on the floor, whichever way it ended.
HISTORY_STATUSES = ("closed", "cancelled")

#: The four tabs of the orders pane (06 Screen 3, D-042).
#:
#: A "draft" view was here and is gone on purpose (`D-122`): a draft is an empty
#: bill, so the tab filtered to bills with nothing on them.
#: The views, and **every one of them is a status** (`D-146`, `D-168`).
#:
#: Open, closed today, refunded today, everything. A bill's *age* is not on this
#: axis: a carried bill is an open bill, and it is reached by asking for it
#: inside the open view rather than by a view of its own — which is what every
#: till of this kind does, Toast included.
VIEWS = ("open", "closed", "returned", "all")

#: How many carried bills one request will fetch at once.
#:
#: The floor is bounded by the business day and cannot grow; the carried ones are
#: bounded by nothing but how long a shop has been leaving bills open, and the
#: measurement in `D-158` puts three thousand of them at four seconds. So they
#: are capped, and **the count beside the switch reports the true total**: a list
#: that says "100" where there are 312 is the lie this whole split exists to
#: remove.
CARRIED_LIMIT = 100

#: A day's history is what a till needs — a reprint, a return, "what did table
#: four have". Anything older is a report, and a report is not this list.
CLOSED_LIMIT = 200

#: What every card is drawn from, whichever tab asked for it.
LIST_FIELDS = (
	"name",
	# What the cashier reads on a card and says out loud (FR-2.10).
	"daily_number",
	"call_name",
	"order_type",
	"status",
	"table",
	"cover_count",
	"customer",
	"cashier",
	"sales_invoice",
	"total_amount",
	"opened_at",
	"closed_at",
)


@frappe.whitelist()
def count_carried_orders(pos_profile: str) -> dict:
	"""How many bills are still open from days that have ended (`D-164`).

	**The count is the whole point of keeping them apart.** A switch labelled
	"show carried" that a cashier has to turn on to find out whether it holds
	three bills or three hundred hides the number as surely as the old mixed list
	did — the shop learns it is carrying a year's worth of bills by feeling the
	screen go slow, which is exactly what `D-158` refused to accept as a warning.

	So the number rides on the switch, always, and this is what puts it there. A
	count rather than a list: it is asked on every refresh, and it must stay cheap
	however many there are.
	"""
	branch = service.branch_of_profile(pos_profile)
	scope: dict = {}

	if branch:
		validate_branch_access(branch)
		scope["branch"] = branch
	else:
		scope["pos_profile"] = pos_profile

	days = _open_days(scope)
	filters = {**scope, "status": ("in", OPEN_STATUSES)}
	if days:
		filters["restaurant_shift"] = ("not in", days)

	return {"carried": frappe.db.count("Restaurant Order", filters)}


@frappe.whitelist()
def list_orders(pos_profile: str, view: str = "open", include_carried: bool | int = 0) -> list[dict]:
	"""The orders this till may look at, in one of four views (06 Screen 3).

	``include_carried`` widens the **open** view to bills whose business day has
	ended (`D-164`). Off by default, so the ordinary list holds one day and
	cannot grow with the age of the shop — and it is a switch rather than a view
	of its own, because a carried bill is an open bill and these views are
	statuses (`D-168`).

	Scoped to the **branch**, not the terminal. An order opened on the waiter's
	tablet has to be payable at the till, and a takeaway opened by the cashier
	who just went on break has to be findable by the one taking over. Scoping
	this to ``pos_profile`` would hide both and strand the order.

	Open orders come oldest first: the one that has been waiting longest is the
	one that needs attention (06 §Screen 1 behaviour). History comes newest
	first and only for the open business day, because what a cashier wants from
	a closed order is the one they just closed.

	**Each tab is bounded by its own event** (`D-146`). "Closed today" means
	closed in the day, and "returns" means refunded in it — not *opened* in it,
	which is what all three history tabs used to measure and is a different day
	for every bill that outlives midnight. **And "the day" is the business day
	from its opening, not the date** (`D-216`): one left open for three dates
	lists all three, as its closing report does.
	"""
	if view not in VIEWS:
		frappe.throw(_("Unknown order view {0}.").format(view))

	branch = service.branch_of_profile(pos_profile)
	scope: dict = {}

	if branch:
		validate_branch_access(branch)
		scope["branch"] = branch
	else:
		# A terminal attached to no section has no branch to scope by. Falling
		# back to the terminal is narrower than right; listing every branch's
		# floor would be wrong.
		scope["pos_profile"] = pos_profile

	# FR-12.x — whose orders a cashier may see is a permission, enforced here
	# and not by hiding a button. But it scopes **history**, not the floor
	# (`D-121`).
	#
	# It used to scope both, and that was wrong twice over. It contradicted this
	# function's own promise two paragraphs up — that a bill left by the cashier
	# who went on break is findable by the one taking over — and it did not even
	# restrict: the floor plan lists a table's bills without asking, so the
	# cashier tapped table eleven and opened the bill this list had hidden. A
	# rule enforced on one screen and not the other is not a rule.
	#
	# So an open bill in the branch belongs to whoever is working, and the
	# permission decides who may read the day's closed ones.
	mine_only = not get_pos_permission_set().get("can_view_all_orders")

	if view == "returned":
		return _refunds_this_day(scope, mine_only=mine_only)

	orders = []
	if view in ("open", "all"):
		orders += _floor(scope)
	if view == "all" or (view == "open" and cint(include_carried)):
		orders += _mark_carried(_carried(scope))
	if view in ("closed", "all"):
		orders += _closed_this_day(scope, mine_only=mine_only)

	if orders:
		_annotate_refunds(orders)
		_annotate_open_orders(orders)

	# **"Everything" has to mean everything** (`D-151`). The tab held the floor
	# and the day's closed bills and quietly left the refunds out, so money that
	# went back out was in no list a cashier could reach from here — the one
	# view named for holding all of them.
	if view == "all":
		orders += _refunds_this_day(scope, mine_only=mine_only)

	# **Every row carries the field, not only the carried ones.** A key that is
	# present on some rows and absent on others makes every reader guess, and the
	# guess is made in three screens. Today's floor, today's closed bills and
	# today's refunds are all *not* carried, and now say so.
	for row in orders:
		row.setdefault("is_carried", 0)

	return orders


#: How far back a search reaches, and how much it may bring home.
#:
#: **Both are the point.** A restaurant that has been open two years holds
#: hundreds of thousands of bills, and the only safe list is one nobody can ask
#: to be long: a window and a limit, always, whatever is typed.
SEARCH_DAYS = 90
SEARCH_LIMIT = 50


@frappe.whitelist()
def search_orders(pos_profile: str, query: str, days: int | str = SEARCH_DAYS) -> list[dict]:
	"""Find a bill the till is no longer showing (`FR-2.14`, `D-152`).

	**Asked for, never automatic.** The tabs are today's work and stay bounded by
	the day; this is the other question — *a company rang about an invoice from
	last week* — and it is answered by a search with a window and a ceiling, not
	by a longer list. That is what every till of this kind does, because the
	alternative is a query that grows with the age of the shop.

	It matches what somebody standing at the counter would actually have: **the
	short number on their receipt**, the invoice number on a company's copy, the
	name it was billed to, the name that was called out — or, when they have
	nothing else, **the amount**.
	"""
	if not (query or "").strip():
		frappe.throw(_("Type something to search for."))

	branch = service.branch_of_profile(pos_profile)
	filters: dict = {
		"status": ("in", HISTORY_STATUSES),
		"closed_at": (">=", add_days(_since_midnight(), -abs(cint(days)))),
	}

	if branch:
		validate_branch_access(branch)
		filters["branch"] = branch
	else:
		filters["pos_profile"] = pos_profile

	# The same rule the closed tab follows (`D-121`): the day's history is the
	# permission's business, and so is anybody else's older history.
	if not get_pos_permission_set().get("can_view_all_orders"):
		filters["cashier"] = frappe.session.user

	orders = frappe.get_all(
		"Restaurant Order",
		filters=filters,
		or_filters=_matching(query.strip()),
		fields=list(LIST_FIELDS),
		order_by="closed_at desc",
		limit=SEARCH_LIMIT,
	)
	if not orders:
		return []

	_annotate_refunds(orders)
	_annotate_open_orders(orders)
	return orders


def _matching(query: str) -> dict:
	"""Every field the person at the counter might be holding.

	`or_filters` rather than one `like` over a concatenation: each of these is
	an indexed column, and a search that scans is a search that stops working
	the year the shop gets busy.
	"""
	terms: dict = {
		"name": ("like", f"%{query}%"),
		"sales_invoice": ("like", f"%{query}%"),
		"call_name": ("like", f"%{query}%"),
	}

	# `121` is the number on the receipt; `48.00` is what they remember when
	# they have lost the receipt entirely.
	number = _as_number(query)
	if number is not None:
		terms["daily_number"] = cint(number)
		terms["total_amount"] = flt(number)

	billed_to = frappe.get_all("Customer", filters={"customer_name": ("like", f"%{query}%")}, pluck="name")
	if billed_to:
		terms["customer"] = ("in", billed_to)

	return terms


def _as_number(query: str) -> float | None:
	try:
		return float(query)
	except ValueError:
		return None


def _since_midnight():
	"""Midnight today — where the search window is measured from."""
	return get_datetime(f"{nowdate()} 00:00:00")


def _day_began(scope: dict):
	"""Where the history tabs start: when the open business day was opened (`D-216`).

	**A day is the period between opening it and closing it in the till, not a
	date.** One opened on the 15th and closed on the 18th is one day, and its
	closing report counts every bill in it — so the tabs a cashier checks that
	report against must hold them too. Measured from midnight, the 15th's closed
	bills left the tab on the 16th while their day was still open.

	With no day open — between closing one and opening the next — midnight.
	"""
	branch = scope.get("branch")
	opened = frappe.get_all(
		"Restaurant Shift",
		filters={"status": "open", **({"branch": branch} if branch else {})},
		fields=["opened_at"],
		order_by="opened_at asc",
		limit=1,
	)
	return opened[0].opened_at if opened else _since_midnight()


def _floor(scope: dict) -> list:
	"""The bills open on **today's** floor, oldest first (`D-164`).

	The one that has been waiting longest needs attention first — and the list
	holds one business day, so it cannot grow with the age of the shop.

	It used to hold every open bill at any age, which stranded two questions in
	one list: *which table do I serve now* and *what was left from days gone by*.
	The forgotten ones sorted to the top of the cashier's work, and the list got
	slower every month a bill was left behind (`D-158`).
	"""
	days = _open_days(scope)
	if not days:
		# No day is open, so nothing is on today's floor. Every open bill belongs
		# to a day that has ended, and is carried.
		return []

	return frappe.get_all(
		"Restaurant Order",
		filters={**scope, "status": ("in", OPEN_STATUSES), "restaurant_shift": ("in", days)},
		fields=list(LIST_FIELDS),
		order_by="opened_at asc",
	)


def _carried(scope: dict) -> list:
	"""Bills still open whose business day has ended (`D-164`, `BR-045`).

	**Not hidden — moved.** They are a different job from serving a table: the
	day they belong to has been counted and reported, so each one is now either
	money to collect or a bill to cancel, and it is somebody's to finish rather
	than nobody's to notice.

	They stay fully payable and editable (`D-105`): carrying a bill is a thing a
	branch may allow, not a thing that freezes it.

	**Newest first — the floor's rule reversed on purpose.** The floor is oldest
	first because the table waiting longest needs serving. Here the newest is the
	one somebody may still walk in and settle, and a bill abandoned a year ago is
	not going to be paid because it sits at the top of a list. Sorted the other
	way against the cap, last night's bill hides behind three hundred dead ones
	and the tab is useless for the only case it gets opened for.
	"""
	days = _open_days(scope)
	filters = {**scope, "status": ("in", OPEN_STATUSES)}
	if days:
		filters["restaurant_shift"] = ("not in", days)

	return frappe.get_all(
		"Restaurant Order",
		filters=filters,
		fields=list(LIST_FIELDS),
		order_by="opened_at desc",
		limit=CARRIED_LIMIT,
	)


def _mark_carried(orders: list) -> list:
	"""Say which side of the business day these bills are on (`D-164`).

	One field, two jobs on the screen. It marks the row in the "everything" tab,
	where both kinds sit together — and it decides whether the **daily number**
	is shown, because that number restarts at one every day: on today's floor it
	names the bill, and on a bill from three days ago two rows can read the same
	(`D-159`). So it is shown where it identifies and withheld where it misleads,
	rather than removed from the screen altogether.
	"""
	for order in orders:
		order["is_carried"] = 1
	return orders


def _open_days(scope: dict) -> list[str]:
	"""The business days still open for whatever this list is scoped to.

	Normally exactly one — `open_day` allows a single day per branch — but read
	as a list rather than assumed, because a second one would otherwise silently
	empty the floor rather than show both.

	A terminal with no branch is scoped by `pos_profile`, which is not a column
	on `Restaurant Shift`; that list falls back to every open day, which is the
	honest answer for a till nobody has placed in a branch.
	"""
	branch = scope.get("branch")
	filters = {"status": "open"}
	if branch:
		filters["branch"] = branch

	return frappe.get_all("Restaurant Shift", filters=filters, pluck="name")


def _closed_this_day(scope: dict, *, mine_only: bool) -> list:
	"""Bills that **ended** in the open business day, newest first.

	`closed_at`, not `opened_at`. A bill opened at eleven last night and paid at
	one in the morning belongs to the shift that took the money, and reading the
	opening time hid it from the tab the moment it was paid — the cashier closed
	a bill and it left the till altogether (`D-146`). And from when the **day**
	opened, not from midnight, however many dates it spans (`D-216`).
	"""
	filters = {**scope, "status": ("in", HISTORY_STATUSES), "closed_at": (">=", _day_began(scope))}
	if mine_only:
		filters["cashier"] = frappe.session.user

	return frappe.get_all(
		"Restaurant Order",
		filters=filters,
		fields=list(LIST_FIELDS),
		order_by="closed_at desc",
		limit=CLOSED_LIMIT,
	)


def _refunds_this_day(scope: dict, *, mine_only: bool) -> list[dict]:
	"""Every refund made in the open business day, one row per credit note (`D-143`, `D-146`, `D-216`).

	**It starts from the credit notes, not from the sales.** The tab used to
	list today's orders and then look for refunds against them, which asked the
	wrong question twice: a bill refunded today but sold yesterday was missing —
	and `BR-055` exists precisely because refunding an older bill is a thing
	that happens, with a manager's PIN — while a bill sold today and refunded
	tomorrow would appear today with nothing on it.

	What the till needs from this tab is the drawer's day: the money that went
	back out since the day opened, reconcilable line by line against a count.
	"""
	credits = frappe.get_all(
		SALE,
		filters={
			"is_return": 1,
			"docstatus": 1,
			"creation": (">=", _day_began(scope)),
			**({"pos_profile": ("in", service.profiles_in(scope["branch"]))} if scope.get("branch") else {}),
		},
		fields=[
			"name",
			"return_against",
			"rpos_daily_number",
			"grand_total",
			"rounded_total",
			"posting_date",
			"creation",
		],
		order_by="creation desc",
		limit=CLOSED_LIMIT,
	)
	if not credits:
		return []

	filters = {**scope, "sales_invoice": ("in", [credit.return_against for credit in credits])}
	if mine_only:
		filters["cashier"] = frappe.session.user

	# The sales the refunds were taken against — and the **authority** on who may
	# see them: a credit note whose bill is not in this branch, or not this
	# cashier's when the permission says so, has no row here.
	sales = frappe.get_all("Restaurant Order", filters=filters, fields=list(LIST_FIELDS))
	_annotate_refunds(sales)
	_annotate_open_orders(sales)

	return _returns_of(credits, {row.sales_invoice: row for row in sales})


def _returns_of(credits: list, by_invoice: dict) -> list[dict]:
	"""One row per credit note, not one per refunded bill (`D-143`).

	This tab used to list the **orders** money had gone back out of, on the
	reasoning that a credit note is not a `Restaurant Order` so no list of
	orders could hold one. The reasoning was sound and answered the wrong
	question: these history tabs are the **day's transactions**, and a refund is
	one. Listing the original instead failed three ways —

	* two refunds on one bill collapsed into a single figure, so the events were
	  invisible;
	* the list could not be reconciled line by line against a drawer that had
	  paid those refunds out;
	* and there was no row to reprint a particular credit note from.

	A refund keeps the card it reverses — the type, the table, the customer are
	all the sale's — and replaces the parts that are its own: its number, its
	time, and an amount that is **negative**, because that is the direction the
	money went.
	"""
	rows = []
	for credit in credits:
		sale = by_invoice.get(credit.return_against)
		if not sale:
			# Not this branch's, or not this cashier's to see.
			continue

		refund = abs(flt(credit.rounded_total or credit.grand_total))

		rows.append(
			{
				**sale,
				# The document this row *is*, replacing the one it came from.
				"name": sale.name,
				"credit_note": credit.name,
				"daily_number": credit.rpos_daily_number or sale.daily_number,
				"total_amount": -refund,
				"returned_amount": refund,
				# **When the refund happened**, in both fields, because the card
				# reads whichever the row has: the sale's own times belong to the
				# sale and would date this row to somebody else's event.
				"opened_at": credit.creation,
				"closed_at": credit.creation,
				# Which bill it reverses, so the row can say so out loud.
				"returns_daily_number": sale.daily_number,
				"is_return": 1,
			}
		)

	return rows


def _annotate_refunds(orders: list) -> None:
	"""How much of each bill went back to the customer (FR-9, D-070).

	One query for the whole list, keyed on `return_against` — the same field
	ERPNext links a credit note by. A refunded bill was invisible in the till
	until now: the credit note is not an order, so no list of orders could ever
	show it, and the cashier saw only the sale.
	"""
	invoices = [row.sales_invoice for row in orders if row.get("sales_invoice")]

	refunded: dict[str, float] = {}
	if invoices:
		for row in frappe.get_all(
			SALE,
			filters={"return_against": ("in", invoices), "docstatus": 1},
			fields=["return_against", "grand_total"],
		):
			refunded[row.return_against] = refunded.get(row.return_against, 0.0) + abs(flt(row.grand_total))

	for order in orders:
		order.returned_amount = refunded.get(order.get("sales_invoice"), 0.0)


def _annotate_open_orders(orders: list) -> None:
	"""Add item count and display labels.

	Three lookups for the whole list rather than three per order: a lunch rush
	is fifty open orders and this list refreshes on every realtime event
	(``04`` §8).
	"""
	names = [row.name for row in orders]

	counts: dict[str, int] = {}
	for row in frappe.get_all(
		"Restaurant Order Item",
		filters={"parent": ("in", names), "parenttype": "Restaurant Order"},
		fields=["parent", "status"],
	):
		if row.status != "void":
			counts[row.parent] = counts.get(row.parent, 0) + 1

	# The terminal already holds the order types it is allowed to open, but an
	# order may carry one this terminal cannot open and still needs to display.
	types = {
		row.name: row
		for row in frappe.get_all(
			"Restaurant Order Type",
			filters={"name": ("in", list({row.order_type for row in orders if row.order_type}))},
			fields=["name", "title", "title_ar", "icon", "color"],
		)
	}

	# The card shows who opened the order, so a cashier taking over a shift can
	# tell their own tables from someone else's at a glance.
	cashiers = {
		row.name: row.full_name
		for row in frappe.get_all(
			"User",
			filters={"name": ("in", list({row.cashier for row in orders if row.cashier}))},
			fields=["name", "full_name"],
		)
	}

	table_numbers = {
		row.name: row.table_number
		for row in frappe.get_all(
			"Restaurant Table",
			filters={"name": ("in", list({row.table for row in orders if row.table}))},
			fields=["name", "table_number"],
		)
	}

	# **Who the bill was billed to** — a company asking for a refund a week later
	# knows its own name long before it knows `RO-2026-09-00342` (`D-152`).
	customers = {
		row.name: row.customer_name
		for row in frappe.get_all(
			"Customer",
			filters={"name": ("in", list({row.customer for row in orders if row.customer}))},
			fields=["name", "customer_name"],
		)
	}

	for order in orders:
		order_type = types.get(order.order_type)
		order.order_type_title = order_type.title if order_type else order.order_type
		order.order_type_title_ar = order_type.title_ar if order_type else order.order_type
		order.icon = order_type.icon if order_type else None
		order.color = order_type.color if order_type else None
		order.table_number = table_numbers.get(order.table)
		order.cashier_name = cashiers.get(order.cashier) or order.cashier
		order.customer_name = customers.get(order.customer)
		order.item_count = counts.get(order.name, 0)


@frappe.whitelist()
def get_order(order_name: str) -> dict:
	"""Full order state for the order screen."""
	order = _load(order_name)
	promoted = promotions.per_line(order)
	return {
		**_summary(order),
		"order_type": order.order_type,
		"table": order.table,
		"table_number": frappe.db.get_value("Restaurant Table", order.table, "table_number")
		if order.table
		else None,
		# Every seat this bill holds, its own first (`BR-063`). The screen needs
		# it to know which tables are already on the party before offering more.
		"tables": service.tables_of(order),
		"section": order.section,
		"customer": order.customer,
		"call_name": order.call_name,
		"daily_number": order.daily_number,
		"delivery_address": order.delivery_address,
		# Where it goes, in words. A driver cannot read `ADDR-00012`.
		"delivery_address_line": customer_service.address_label(order.delivery_address),
		"customer_mobile": frappe.db.get_value("Customer", order.customer, "mobile_no")
		if order.customer
		else None,
		# The bill names the customer, and a Customer's id is not their name
		# (06 Screen 3).
		"customer_name": frappe.db.get_value("Customer", order.customer, "customer_name")
		if order.customer
		else None,
		"cover_count": order.cover_count,
		"notes": order.notes,
		"opened_at": order.opened_at,
		"items": [
			{
				"idx": row.idx,
				"item": row.item,
				"item_name": row.item_name,
				"qty": row.qty,
				"rate": row.rate,
				"amount": row.amount,
				"status": row.status,
				"notes": row.notes,
				"modifiers": frappe.parse_json(row.modifiers) if row.modifiers else [],
				"production_center": row.production_center,
				# **Which lines the offer reached** (`D-166`). A bill that says
				# "-13.00" at the bottom does not say which dish it came off, and
				# that is the question the guest asks while pointing at one.
				"promotion_amount": promoted.get(row.idx, 0.0),
			}
			for row in order.items
		],
		# A ticket whose paper never came is said on the order itself (`D-211`),
		# not left on a desk form nobody opens during service.
		**kitchen.print_state(order.name),
	}

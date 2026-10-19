# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Kitchen Order Tickets.

``FR-6.3``: group the order's items by their resolved Production Center and
raise one KOT per center. ``BR-073`` defines the four types — initial,
addition, void, reprint.

This module creates the documents, announces them to the KDS, and hands each one
to ``utils.printing``. It does not talk to a printer itself — nothing on the
server does (``D-084``). A ticket is rendered here and sent by an agent inside
the restaurant, so ``print_status`` stays ``pending`` until that agent reports
back (``FR-7.3``, ``BR-072``).

**Printing never fails an order.** ``print_kot`` swallows its own errors: a
station whose printer is unplugged still gets the ticket on its screen, and the
customer is still charged.

Prices never appear on a KOT (``BR-075``). The header carries order number,
table, order type, cashier and timestamp (``BR-074``).

Refs: BR-073, BR-074, BR-075, FR-2.3, FR-2.4, FR-2.5, FR-6.3, FR-6.4
"""

import frappe
from frappe import _
from frappe.query_builder import Order
from frappe.utils import cint, flt, now_datetime

from restaurant_pos.utils import activity, combos, printing, routing
from restaurant_pos.utils.audit import log_audit

#: Lines that still have to reach the kitchen.
PENDING = "pending"
SENT = "sent"
VOID = "void"


def print_state(order_name: str) -> dict:
	"""How many of an order's tickets are still on their way to paper (`D-211`).

	The order screen checks back while this is above zero, and stops. What did
	**not** print is not said here any more: it is the bell's, for the whole
	branch (`D-298`) — a banner per ticket on the bill stood over the items for
	as long as a printer stayed off.

	`pending` on a station that asked for no paper is not on its way anywhere,
	so it is not counted.
	"""
	printing = 0
	branch = frappe.db.get_value("Restaurant Order", order_name, "branch")
	for ticket in frappe.get_all(
		"Kitchen Order Ticket",
		filters={"restaurant_order": order_name, "print_status": PENDING},
		fields=["production_center"],
	):
		if prints_on_send(ticket.production_center, branch):
			printing += 1

	return {"tickets_printing": printing}


def station_of(production_center: str | None) -> tuple[str, str]:
	"""A ticket's station as the cashier names it, in English and Arabic.

	No station is the cashier's printer (`BR-070` level 7, `D-300`).
	"""
	if not production_center:
		return "Cashier printer", _("Cashier printer")
	center = frappe.get_cached_doc("Production Center", production_center)
	return center.title, center.title_ar or center.title


def prints_on_send(production_center: str | None, branch: str | None = None) -> bool:
	"""Whether a new ticket goes to paper by itself.

	A station decides for itself. A ticket with none goes to the cashier's
	printer (`D-300`) — **in a branch that has a kitchen** (`D-364`): there an
	item nobody routed is a slip in the setup, and paper is how it still reaches
	the cook. A branch with no station at all — a counter, a café — has no
	kitchen to reach, and nothing is assumed for it: no paper, no job.
	"""
	if production_center:
		return bool(frappe.get_cached_doc("Production Center", production_center).auto_print_on_send)
	return has_kitchen(branch) if branch else True


def has_kitchen(branch: str | None) -> bool:
	"""Whether this branch has any station to cook at (`D-364`)."""
	return bool(branch) and bool(frappe.db.exists("Production Center", {"branch": branch, "is_active": 1}))


def queue_paper(kot, order, *, force: bool = False) -> None:
	"""Put a ticket on its way to paper — **only if there is paper to put it on** (`D-364`).

	The load test queued two jobs a sale in a branch with no printer at all, and
	each found out only once it ran that there was nothing to do: 737 of them
	stood in front of the posting. Asked here, before the job: a station that
	wants no paper gets no job; a ticket that wants paper and has no printer is
	marked failed at once, so the bell says it (`D-298`) without a job to say it.
	"""
	if not force and not prints_on_send(kot.production_center, order.branch):
		return
	if not printing.kot_printer(kot.production_center, order.pos_profile):
		printing.mark_kot_failed(kot.name)
		return
	# `force` only when asked: a new ticket's job is the plain one it always was.
	printing.enqueue_print("print_kot", kot_name=kot.name, **({"force": True} if force else {}))


#: Alerts on one page of the bell when the settings say nothing (`D-298`).
ALERT_PAGE = 20


def alerts_per_page() -> int:
	"""The bell's page, from the settings (`D-301`) — the next page is asked for, never sent unasked."""
	return cint(frappe.db.get_single_value("Restaurant POS Settings", "alerts_per_page")) or ALERT_PAGE


def print_alerts(branch: str, limit: int) -> list[dict]:
	"""The newest ``limit`` tickets in the branch that failed to print (`D-298`).

	One of the bell's two sources; `utils/bell.feed` pages them together with
	the office's announcements (`D-303`).

	**One place for the whole branch**, not a banner per order. The banner said
	it only on the bill in hand, one line per ticket, and stood there until
	paper came — which on a printer that stays off is for ever, over the items.
	Simphony puts the same alert behind one flashing button; this is that button.

	**Read off the ticket, not off its print jobs.** The first version listed
	tickets with a failed job, and a station with no printer at all fails
	without ever making one — the badge counted it and the list could not show
	it. `print_failed_at` is written on every road to `failed`.

	**A log, not only what is outstanding.** A ticket that failed and was then
	reprinted, or that the cashier said they told the kitchen about, stays on
	the list with how it ended — the manager reading it after service sees what
	happened, not only what is still wrong. Which of them this till has read is
	the till's own business (`D-299`), so the badge is counted there.

	**Only the newest ``limit``**, read through the index on ``print_failed_at``
	however many thousand there are (`D-301`).
	"""
	ticket = frappe.qb.DocType("Kitchen Order Ticket")
	rows = (
		_in_branch(ticket, branch)
		.select(
			ticket.name,
			ticket.restaurant_order,
			ticket.production_center,
			ticket.print_status,
			ticket.daily_number,
			ticket.call_name,
			ticket.table,
			ticket.kitchen_told_by,
			ticket.print_failed_at,
		)
		.where(ticket.print_failed_at.isnotnull())
		# The name breaks a tie, so a page boundary never shows one ticket twice.
		.orderby(ticket.print_failed_at, order=Order.desc)
		.orderby(ticket.name, order=Order.desc)
		.limit(limit)
		.run(as_dict=True)
	)

	alerts = []
	for row in rows:
		station, station_ar = station_of(row.production_center)
		alerts.append(
			{
				"kind": "print",
				"key": row.name,
				"at": row.print_failed_at,
				"kot_name": row.name,
				"restaurant_order": row.restaurant_order,
				"daily_number": row.daily_number,
				"call_name": row.call_name,
				"table_number": row.table
				and frappe.get_cached_value("Restaurant Table", row.table, "table_number"),
				"station": station,
				"station_ar": station_ar,
				"failed_at": row.print_failed_at,
				"state": _alert_state(row),
			}
		)

	return alerts


def _alert_state(ticket) -> str:
	"""How an unprinted ticket ended, in the one word the bell shows."""
	if ticket.print_status == "printed":
		return "printed"
	if ticket.print_status == PENDING:
		return "printing"
	return "told" if ticket.kitchen_told_by else "failed"


def _in_branch(ticket, branch: str):
	"""Tickets of this branch's bills, asked by the relation (`D-210`'s lesson):
	a list of every order name in the branch is not handed to a filter."""
	order = frappe.qb.DocType("Restaurant Order")
	return (
		frappe.qb.from_(ticket)
		.join(order)
		.on(order.name == ticket.restaurant_order)
		.where(order.branch == branch)
	)


def mark_kitchen_told(kot_name: str) -> dict:
	"""The cashier told the kitchen by hand, so the ticket stops alerting (`D-298`).

	Simphony asks the same of its operator: confirm the items did not reach the
	kitchen, and tell the kitchen. **Recorded, not hidden** — the ticket keeps
	`failed`, because the paper never came, and says who answered for it and
	when; the bill's story says it too.
	"""
	kot = frappe.db.get_value(
		"Kitchen Order Ticket",
		kot_name,
		["name", "restaurant_order", "production_center", "print_status"],
		as_dict=True,
	)
	if kot.print_status != "failed":
		frappe.throw(_("This ticket is not waiting on the kitchen."))

	frappe.db.set_value(
		"Kitchen Order Ticket",
		kot.name,
		{"kitchen_told_by": frappe.session.user, "kitchen_told_at": now_datetime()},
		update_modified=False,
	)
	activity.log(kot.restaurant_order, "kitchen_told", subject=station_of(kot.production_center)[1])
	return {"kot_name": kot.name, "state": "told"}


def send_to_kitchen(order, *, kot_type: str | None = None) -> dict:
	"""Raise a KOT per production center for everything not yet sent.

	Returns the created tickets plus any items that no rule could route, which
	fall to the cashier's printer under ``BR-070`` level 7.
	"""
	pending = [row for row in order.items if row.status == PENDING]
	if not pending:
		frappe.throw(_("There is nothing new to send to the kitchen."))

	kot_type = kot_type or _kot_type_for(order)
	header = _header(order)

	routed = _split_by_center(_tickets_of(order, pending))
	unrouted = routed.get(None, [])
	created = []
	named: set[int] = set()

	for production_center, rows in routed.items():
		kot = _create_kot(
			order,
			kot_type=kot_type,
			production_center=production_center,
			rows=rows,
			header=header,
			action="add",
		)
		created.append(kot)

		for row in rows:
			# A combo's items reach several tickets; its line names the first.
			if id(row.source) not in named:
				named.add(id(row.source))
				row.source.kot_reference = kot.name

	moment = now_datetime()
	for row in pending:
		row.status = SENT
		row.sent_at = moment

	if order.status in ("draft", "active"):
		order.status = "in_kitchen"

	order.save(ignore_permissions=True)

	for kot in created:
		_announce(kot)
		queue_paper(kot, order)

	# Station **names**, not ids. `PC-001, PC-007` is not a sentence anybody
	# reads — the same lesson the kitchen ticket taught (`D-087`).
	stations = sorted({station_of(kot.production_center)[1] for kot in created})

	activity.log(
		order,
		"sent_to_kitchen",
		subject="، ".join(stations),
		details={"kots": [k.name for k in created], "unrouted": [r.item_name for r in unrouted]},
	)

	return {
		"kots_created": [
			{
				"kot_name": kot.name,
				"production_center": kot.production_center,
				"kot_type": kot.kot_type,
				"print_status": kot.print_status,
			}
			for kot in created
		],
		# BR-070 level 7. Surfaced rather than swallowed: an item nobody routed
		# went to the cashier's printer, not to a station (`D-300`) — said only
		# where there is a kitchen it should have gone to (`D-364`).
		"unrouted_items": [row.item_name for row in unrouted] if has_kitchen(order.branch) else [],
	}


def create_void_kot(order, rows) -> list[dict]:
	"""Tell the kitchen to drop lines it has already been given (BR-013).

	Called when a line that reached the kitchen is voided, and for every sent
	line when the whole order is cancelled.
	"""
	rows = [row for row in rows if row.kot_reference or row.sent_at]
	if not rows:
		return []

	header = _header(order)
	routed = _split_by_center(_tickets_of(order, rows))

	created = []
	for production_center, center_rows in routed.items():
		kot = _create_kot(
			order,
			kot_type="void",
			production_center=production_center,
			rows=center_rows,
			header=header,
			action="void",
		)
		created.append(kot)
		_announce(kot)
		# A void ticket that only reaches the screen leaves the cook working from
		# paper that is now wrong — which is the exact plate this is meant to stop.
		queue_paper(kot, order, force=True)

	return [
		{"kot_name": kot.name, "production_center": kot.production_center, "kot_type": "void"}
		for kot in created
	]


def reprint(kot_name: str) -> dict:
	"""Queue an existing ticket to be printed again (FR-6.4).

	No second document is created: a reprint is the same ticket on paper twice,
	and a duplicate would distort the kitchen's history. The trail lives in the
	audit log, and the ticket carries a REPRINT header because its ``kot_type``
	is on the template (``DECISIONS.md`` D-021).

	``force`` because a reprint is somebody asking for paper: whether the station
	prints automatically is a rule about new tickets, not about this request.
	"""
	kot = frappe.get_doc("Kitchen Order Ticket", kot_name)
	order = frappe.db.get_value(
		"Restaurant Order", kot.restaurant_order, ["branch", "pos_profile"], as_dict=True
	)

	# A fresh try is a fresh question: if this one fails too, the bell says so
	# again rather than keeping the earlier "the kitchen was told" (`D-298`).
	kot.db_set(
		{"print_status": "pending", "kitchen_told_by": None, "kitchen_told_at": None},
		update_modified=False,
	)
	queue_paper(kot, order, force=True)

	log_audit(
		"reprint_receipt",
		branch=order.branch,
		pos_profile=order.pos_profile,
		restaurant_order=kot.restaurant_order,
		details={"kot": kot.name, "production_center": kot.production_center},
	)

	_announce(kot, reprint=True)
	return {"kot_name": kot.name, "print_status": "pending", "reprint": True}


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _kot_type_for(order) -> str:
	"""BR-073 — the first send is initial, anything after it is an addition."""
	already_sent = any(row.status in (SENT, VOID) and row.sent_at for row in order.items)
	return "addition" if already_sent else "initial"


def _header(order) -> frappe._dict:
	"""BR-074 — what the kitchen needs to identify the ticket.

	Arabic titles, because the kitchen reads the ticket and printing is
	Arabic-first (``FR-7.4``).
	"""
	return frappe._dict(
		order_type_title=frappe.db.get_value("Restaurant Order Type", order.order_type, "title_ar"),
		cashier_name=frappe.db.get_value("User", order.cashier, "full_name"),
		table=order.table,
		# What the counter shouts when it is ready (FR-2.10, FR-2.11).
		daily_number=order.daily_number,
		call_name=order.call_name,
		# On **every** station's ticket, not one of them. An allergy, or a "rush
		# this", that reached only the grill is exactly the case an item note
		# cannot cover — and the reason order-level notes exist (FR-2.9).
		order_notes=order.notes,
	)


def _tickets_of(order, rows) -> list[frappe._dict]:
	"""What each station is told, line by line — a combo taken apart (`D-285`).

	A combo is one line on the order, but its burger is cooked at the grill and
	its drink poured at the bar. Each item goes to the station its own routing
	names, as Square's combo does, and says which meal it belongs to so the
	counter can put the tray together.
	"""
	tickets = []
	for row in rows:
		parts = combos.parts(row)
		if not parts:
			tickets.append(
				frappe._dict(
					item=row.item,
					item_name=row.item_name,
					qty=row.qty,
					modifiers=row.modifiers,
					notes=row.notes,
					production_center=row.production_center,
					source=row,
				)
			)
			continue

		label = _("From: {0}").format(row.item_name)
		for part in parts:
			route = routing.resolve_route(
				part["item"], branch=order.branch, order_type=order.order_type, pos_profile=order.pos_profile
			)
			tickets.append(
				frappe._dict(
					item=part["item"],
					item_name=part.get("option_ar") or part["item"],
					qty=flt(row.qty) * (flt(part.get("item_qty")) or 1),
					# `D-289` — the item's own add-ons go to its station with it.
					modifiers=frappe.as_json(part["modifiers"]) if part.get("modifiers") else None,
					notes="\n".join(filter(None, [label, row.notes])),
					production_center=route.production_center,
					source=row,
				)
			)
	return tickets


def _split_by_center(rows) -> dict:
	"""Group rows by production center; rows no rule routed share the key ``None``.

	**They still get a ticket** (`BR-070` level 7, `D-300`). They used to come
	back on their own and go nowhere: the cashier was told they would print on
	the cashier's printer, and nothing printed — a Fanta that reached no one,
	and no alert, because no ticket existed to fail. A ticket with no station
	prints on the cashier's printer, and fails into the bell like any other.
	"""
	grouped: dict = {}
	for row in rows:
		grouped.setdefault(row.production_center or None, []).append(row)
	return grouped


def _create_kot(order, *, kot_type, production_center, rows, header, action):
	kot = frappe.get_doc(
		{
			"doctype": "Kitchen Order Ticket",
			"restaurant_order": order.name,
			"kot_type": kot_type,
			"production_center": production_center,
			"table": header.table,
			"daily_number": header.daily_number,
			"call_name": header.call_name,
			"order_type_title": header.order_type_title,
			"cashier_name": header.cashier_name,
			"order_notes": header.order_notes,
			"sent_at": now_datetime(),
			"print_status": "pending",
			"items": [
				{
					"item": row.item,
					"item_name": row.item_name,
					"qty": flt(row.qty),
					"modifiers": row.modifiers,
					"notes": row.notes,
					"action": action,
				}
				for row in rows
			],
		}
	)
	kot.insert(ignore_permissions=True)
	return kot


def _announce(kot, *, reprint: bool = False) -> None:
	"""Push to the KDS channel for this production center (07 §9).

	Realtime is a notification, not the delivery mechanism: a KDS that missed
	the event still finds the ticket by querying.
	"""
	if not kot.production_center:
		return  # No station, so no screen listening for it (`D-300`).

	frappe.publish_realtime(
		event="rpos:new_kot",
		message={
			"kot": kot.name,
			"kot_type": kot.kot_type,
			"restaurant_order": kot.restaurant_order,
			"table": kot.table,
			"reprint": reprint,
		},
		room=f"rpos:pc:{kot.production_center}",
	)


def restamp_order(order, previous_title: str | None = None) -> list[dict]:
	"""Correct the tickets a station already holds after the order changed type.

	A dine-in plate that becomes a takeaway leaves the kitchen in a bag, and the
	ticket on the rail still says otherwise. The header is corrected in place and
	the station is told, so a KDS re-renders and a reprint shows the truth.

	No new ticket: nothing about the food changed, and a second ticket for the
	same items is how a kitchen cooks an order twice (BR-073). A printed notice
	on paper belongs with the rest of Phase 3.
	"""
	header = _header(order)

	tickets = frappe.get_all(
		"Kitchen Order Ticket",
		filters={"restaurant_order": order.name, "kot_type": ("!=", "void")},
		fields=["name", "production_center"],
	)

	for ticket in tickets:
		frappe.db.set_value(
			"Kitchen Order Ticket",
			ticket.name,
			{
				"order_type_title": header.order_type_title,
				"table": header.table,
				"call_name": header.call_name,
				"order_notes": header.order_notes,
			},
			update_modified=False,
		)

		frappe.publish_realtime(
			event="rpos:kot_updated",
			message={
				"kot": ticket.name,
				"restaurant_order": order.name,
				"table": header.table,
				"order_type_title": header.order_type_title,
				"was_order_type_title": previous_title,
			},
			room=f"rpos:pc:{ticket.production_center}",
		)

	return [{"kot_name": ticket.name, "production_center": ticket.production_center} for ticket in tickets]


def restamp_item(order, row) -> list[dict]:
	"""Correct one line's note on the ticket the station is holding (FR-2.9).

	No new ticket: nothing was added or withdrawn, and a second ticket for the
	same dish is how a kitchen cooks an order twice (BR-073). The row on the
	existing ticket is corrected and the station is told, so a KDS re-renders
	and a reprint shows the truth.
	"""
	if not row.kot_reference:
		return []

	if combos.parts(row):
		return _restamp_combo(order, row)

	target = frappe.db.get_value(
		"KOT Item",
		{"parent": row.kot_reference, "parenttype": "Kitchen Order Ticket", "item": row.item},
		"name",
	)
	if not target:
		return []

	frappe.db.set_value("KOT Item", target, "notes", row.notes, update_modified=False)

	center = frappe.db.get_value("Kitchen Order Ticket", row.kot_reference, "production_center")
	frappe.publish_realtime(
		event="rpos:kot_updated",
		message={
			"kot": row.kot_reference,
			"restaurant_order": order.name,
			"item": row.item,
			"notes": row.notes,
		},
		room=f"rpos:pc:{center}",
	)

	return [{"kot_name": row.kot_reference, "production_center": center}]


def _restamp_combo(order, row) -> list[dict]:
	"""A combo's note, corrected on every station its items went to (`D-285`).

	Its tickets name the items, never the combo, so looking the combo up on its
	first ticket found nothing and the corrected note reached no kitchen at all.
	Each item's row carries «From: <combo>» first, which is how it is found.
	"""
	label = _("From: {0}").format(row.item_name)
	tickets = frappe.get_all(
		"Kitchen Order Ticket",
		filters={"restaurant_order": order.name, "kot_type": ("!=", "void")},
		fields=["name", "production_center"],
	)
	touched = []
	for ticket in tickets:
		for kot_item in frappe.get_all(
			"KOT Item",
			filters={
				"parent": ticket.name,
				"parenttype": "Kitchen Order Ticket",
				"item": ("in", [part["item"] for part in combos.parts(row)]),
				"notes": ("like", f"{label}%"),
			},
			fields=["name", "item"],
		):
			notes = "\n".join(filter(None, [label, row.notes]))
			frappe.db.set_value("KOT Item", kot_item.name, "notes", notes, update_modified=False)
			frappe.publish_realtime(
				event="rpos:kot_updated",
				message={
					"kot": ticket.name,
					"restaurant_order": order.name,
					"item": kot_item.item,
					"notes": notes,
				},
				room=f"rpos:pc:{ticket.production_center}",
			)
			touched.append({"kot_name": ticket.name, "production_center": ticket.production_center})
	return touched

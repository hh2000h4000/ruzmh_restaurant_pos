# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The business day, and the tills that work inside it (FR-8.1..8.3, D-047).

**Two levels, because they answer two questions.**

* A **till session** is one cashier, one terminal, one drawer. It answers *who
  had the money and what is the difference*. Several in a day.
* A **business day** is the branch. It answers *what did we take today* — the
  revenue, the tax, the Z-report. One per branch per day.

Merging them fails in one direction or the other. Day only, and two cashiers
share a single count so a shortage cannot be pinned on anybody. Till only, and
three cashiers make three "days" with no boundary for the books.

**The till session is ERPNext's, not ours.** ``POS Opening Entry`` and
``POS Closing Entry`` are keyed on ``pos_profile`` + ``user``, and
``POS Closing Entry Detail`` is literally *mode of payment · opening · expected
· closing · difference*. That is a till session field for field, so there is
nothing to invent: our till session **is** the opening entry, with a link back
to the day it belongs to. The count then shows up in ERPNext's own POS reports.

ERPNext has no business-day document for POS — its day is a posting date — so
that level stays ``Restaurant Shift``.

**Credit never enters the count** (``D-029``, ``D-046``). A delivery platform
has already taken the customer's money; nothing of it is in the drawer. It is
reported and excluded from the reconciliation, or every close would show a
shortfall the size of the day's app orders and the variance figure would come
to mean nothing.

Refs: FR-8.1, FR-8.2, FR-8.3, BR-040..BR-045, D-029, D-046, D-047
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime, nowdate, nowtime

from restaurant_pos.utils import printing
from restaurant_pos.utils.order import table_section_branch
from restaurant_pos.utils.payment import is_credit_method
from restaurant_pos.utils.permissions import (
	assert_permission,
	server_rights,
	validate_branch_access,
)
from restaurant_pos.utils.totals import money

#: An order still on the floor. Closing over one strands a bill nobody can pay.
OPEN_ORDER_STATUSES = ("draft", "active", "in_kitchen", "pending_payment")


# --------------------------------------------------------------------------- #
# What the screen asks first
# --------------------------------------------------------------------------- #


def shift_state(pos_profile: str) -> dict:
	"""Both levels in one answer, because the screen shows both at once."""
	profile = _profile(pos_profile)
	validate_branch_access(profile.branch)

	day = _open_day(profile)
	till = _open_till(profile)

	return {
		"branch": profile.branch,
		"shift_type": profile.branch_shift_type,
		"settlement_required": bool(profile.settlement_required),
		"day": _day_state(day),
		"till": _till_state(till),
	}


def _day_state(day) -> dict:
	if not day:
		return {"open": False}

	return {
		"open": True,
		"shift": day.name,
		"title": day.title,
		"opened_by": day.opened_by,
		"opened_by_name": frappe.db.get_value("User", day.opened_by, "full_name"),
		"opened_at": day.opened_at,
		"is_mine": day.opened_by == frappe.session.user,
	}


def _till_state(till) -> dict:
	if not till:
		return {"open": False}

	return {
		"open": True,
		"entry": till.name,
		"user": till.user,
		"user_name": frappe.db.get_value("User", till.user, "full_name"),
		"opened_at": till.period_start_date,
		"is_mine": till.user == frappe.session.user,
	}


# --------------------------------------------------------------------------- #
# The business day
# --------------------------------------------------------------------------- #


def open_day(*, pos_profile: str, title: str | None = None) -> dict:
	"""Start the branch's day (FR-8.1, BR-040).

	One per branch: a second would split the day's takings across two reports,
	neither of which balances. A terminal arriving later joins the open one.
	"""
	assert_permission("can_open_shift")

	profile = _profile(pos_profile)
	validate_branch_access(profile.branch)

	existing = _open_day(profile)
	if existing:
		_point_terminal_at(pos_profile, existing.name)
		return {"shift": existing.name, "joined": True}

	day = frappe.get_doc(
		{
			"doctype": "Restaurant Shift",
			"title": title or _("Day {0}").format(nowdate()),
			"branch": profile.branch,
			"shift_date": nowdate(),
			"shift_type": "full_day",
			"status": "open",
			"opened_by": frappe.session.user,
			"opened_at": now_datetime(),
		}
	)
	day.insert(ignore_permissions=True)

	_point_terminal_at(pos_profile, day.name)
	return {"shift": day.name, "joined": False}


def close_day(*, shift_name: str, force: bool = False, pos_profile: str | None = None) -> dict:
	"""End of day (FR-8.2, BR-043, BR-045).

	Any till still open under it is closed first, at its expected figures. A day
	that ended while a drawer was open would leave a count nobody ever made, and
	the cashier who left is not coming back to make it.
	"""
	day = frappe.get_doc("Restaurant Shift", shift_name)
	validate_branch_access(day.branch)

	if day.status == "closed":
		frappe.throw(_("Day {0} is already closed.").format(shift_name))

	assert_permission("can_close_shift")
	# BR-045 — somebody else's day is not yours to end.
	if day.opened_by != frappe.session.user:
		assert_permission("can_close_others_shift")

	# **The branch decides** (`D-105`). A bill still open at closing time is an
	# ordinary evening in one restaurant and an incident in another: a table that
	# walked out, or a tab that genuinely runs past midnight. With the setting on
	# the day waits for them; with it off they carry over and stay fully
	# editable tomorrow.
	report = summarise(shift_name)
	still_open = report["orders"]["still_open"]

	if still_open and _must_finish_orders(day.branch):
		# **And the way past it is a right, not a tick box** (`D-156`). It was a
		# tick box: the screen drew "close the day anyway" beside the count for
		# whoever was standing there, and `can_close_shift` ships **on** for a
		# plain cashier — so the branch setting was a suggestion. A day closed
		# over bills nobody meant to carry cannot be undone.
		if not force:
			frappe.throw(
				_("{0} orders are still open on this day.").format(still_open),
				frappe.ValidationError,
			)

		assert_permission("can_close_day_with_open_orders")

	# **And a branch that carries them over is told the number, not refused it**
	# (`D-158`). A ceiling stood here for an hour and the user was right to
	# reject it: a pile of carried bills makes the till's list slow, and ending
	# the business day is an accounting act. Refusing one for the other stops a
	# manager closing their day at two in the morning over a list that is merely
	# long — a fault we would have caused, worse than the four seconds we would
	# have prevented.

	closed_tills = []
	for entry in _tills_of(shift_name, status="Open"):
		closed_tills.append(close_till(opening_entry=entry, closing_the_day=True)["closing_entry"])

	# Re-read: closing the tills is what settled their counts.
	report = summarise(shift_name)

	day.status = "closed"
	day.closed_by = frappe.session.user
	day.closed_at = now_datetime()
	day.total_sales = report["sales"]
	day.total_orders = report["orders"]["closed"]
	day.total_voids = report["voids"]
	day.settlement_data = frappe.as_json({"report": report, "tills": closed_tills})
	day.save(ignore_permissions=True)

	# Read before the loop below clears them: an audit row names the terminal an
	# action happened on, and by the time the sweep runs none of these still
	# points at the day.
	terminals = frappe.get_all("POS Profile", filters={"restaurant_shift": shift_name}, pluck="name")

	# The terminal stops selling the moment the day ends (BR-044).
	for profile in terminals:
		frappe.db.set_value("POS Profile", profile, "restaurant_shift", None, update_modified=False)

	# **And the people, like the drawers** (`D-178`). The paragraph above says a
	# day that ended over an open till leaves a count nobody made; a day that
	# ended over an open clock-in leaves hours nobody worked, running until
	# somebody notices. The manager closing the day is the only thing in the
	# building that knows the shift is over.
	from restaurant_pos.utils import attendance

	# The terminal it was closed from, when the caller knows it; otherwise one
	# of the day's own. An audit row requires a terminal, and a branch with one
	# till — which is most of them — loses nothing to the fallback.
	sent_home = attendance.clock_out_everyone(
		day.branch,
		at=day.closed_at,
		pos_profile=pos_profile or (terminals[0] if terminals else None),
	)

	# **And the bookings nobody came for** (`D-191`). The same moment and the
	# same reason as the clock-ins above: the evening is over, and only the
	# person closing the day knows it. Marked as the system's, not a host's.
	from restaurant_pos.utils import reservation

	no_shows = reservation.close_out(day.branch, at=day.closed_at)

	return {
		"shift": day.name,
		"report": report,
		"closed_tills": closed_tills,
		"clocked_out": sent_home,
		"no_shows": no_shows,
	}


# --------------------------------------------------------------------------- #
# The till session
# --------------------------------------------------------------------------- #


def open_till(*, pos_profile: str, opening_floats: dict | None = None) -> dict:
	"""Take the drawer (FR-8.1 step 3).

	Opens the day too if nobody has: the first cashier of the morning should
	press one button, not two, and the day is implied by there being a till.

	``Branch.shift_type`` decides whether a second drawer may be open at once —
	``multi`` gives every cashier their own, ``single`` shares one and the next
	cashier joins it (BR-041).
	"""
	assert_permission("can_open_shift")

	profile = _profile(pos_profile)
	validate_branch_access(profile.branch)

	day = _open_day(profile)
	if not day:
		opened = open_day(pos_profile=pos_profile)
		day = frappe.db.get_value(
			"Restaurant Shift", opened["shift"], ["name", "branch", "opened_by"], as_dict=True
		)
	else:
		_point_terminal_at(pos_profile, day.name)

	existing = _open_till(profile)
	if existing:
		if profile.branch_shift_type == "single" or existing.user == frappe.session.user:
			return {"entry": existing.name, "shift": day.name, "joined": True}

		frappe.throw(
			_("{0} still has the till open. Close it before taking over.").format(
				frappe.db.get_value("User", existing.user, "full_name") or existing.user
			)
		)

	entry = frappe.get_doc(
		{
			"doctype": "POS Opening Entry",
			"period_start_date": now_datetime(),
			"posting_date": nowdate(),
			"company": profile.company,
			"pos_profile": pos_profile,
			"user": frappe.session.user,
			"rpos_restaurant_shift": day.name,
			"balance_details": [
				{"mode_of_payment": method, "opening_amount": amount}
				for method, amount in _clean_floats(opening_floats).items()
			]
			# The child table is mandatory, so a shop that keeps no float still
			# says so rather than being unable to open a drawer at all.
			or [{"mode_of_payment": _default_method(pos_profile), "opening_amount": 0}],
		}
	)
	entry.insert(ignore_permissions=True)
	entry.submit()

	# The float has to go in, so the drawer has to open (`D-093`).
	printing.open_drawer(pos_profile, reason="shift opened")

	return {"entry": entry.name, "shift": day.name, "joined": False}


def close_till(
	*,
	opening_entry: str,
	counted: dict | None = None,
	variance_reason: str | None = None,
	closing_the_day: bool = False,
) -> dict:
	"""Hand the drawer back, and account for it (FR-8.2, BR-042, BR-043).

	``closing_the_day`` is the end-of-day sweep closing a drawer its cashier
	left open: it settles at the expected figures rather than demanding a count
	from somebody who is not there.
	"""
	entry = frappe.get_doc("POS Opening Entry", opening_entry)
	profile = _profile(entry.pos_profile)
	validate_branch_access(profile.branch)

	if entry.status != "Open":
		frappe.throw(_("This till session is already closed."))

	if not closing_the_day:
		assert_permission("can_close_shift")
		# BR-045 — a drawer that was not in your hands is not yours to count.
		if entry.user != frappe.session.user:
			assert_permission("can_close_others_shift")

	report = summarise_till(opening_entry)
	settlement = _reconcile(
		report, counted, wants_count=bool(profile.settlement_required) and not closing_the_day
	)

	if settlement["variance"] and not (variance_reason or "").strip():
		frappe.throw(_("Enter a reason for the difference before closing."))

	closing = frappe.get_doc(
		{
			"doctype": "POS Closing Entry",
			"period_start_date": entry.period_start_date,
			"period_end_date": now_datetime(),
			"posting_date": nowdate(),
			"posting_time": nowtime(),
			"company": entry.company,
			"pos_profile": entry.pos_profile,
			"user": entry.user,
			"pos_opening_entry": entry.name,
			"payment_reconciliation": [
				{
					"mode_of_payment": row["method"],
					"opening_amount": row["opening"],
					"expected_amount": row["expected"],
					"closing_amount": row["counted"] if row["counted"] is not None else row["expected"],
					"difference": row["variance"] or 0,
				}
				for row in settlement["methods"]
			],
			# Deliberately empty: our sales are Sales Invoices with `is_pos`, not
			# POS Invoices (D-022), so there is nothing for ERPNext to
			# consolidate — they are submitted and settled already. Verified that
			# ERPNext submits the entry without them.
			"pos_transactions": [],
			"grand_total": report["sales"],
			"net_total": report["sales"],
			"total_quantity": 0,
		}
	)
	closing.insert(ignore_permissions=True)

	# **The drawer could not be handed back by the person holding it** (`D-157`).
	# Submitting reaches ERPNext's `update_opening_entry`, which loads the
	# `POS Opening Entry` fresh and **saves it as whoever is standing there** —
	# and no POS role has desk rights on an accounting document, by design
	# (`08_Security.md` §1). So every real cashier died here on a bare
	# `PermissionError`, and with them every end of day, because closing the day
	# sweeps up the drawers first. Invisible to the suite: every test here ran as
	# Administrator, who passes every check on the first line.
	#
	# The entry above is inserted **before** the borrowing, so it still carries
	# the cashier's name. Same door as `D-144`, and the narrowest one that opens.
	with server_rights():
		closing.submit()

	if (variance_reason or "").strip():
		# Written after submit rather than before: ERPNext's closing entry has no
		# field of its own for it, so this is our custom field (BR-043).
		frappe.db.set_value(
			"POS Closing Entry",
			closing.name,
			"rpos_variance_reason",
			variance_reason.strip(),
			update_modified=False,
		)

	return {
		"closing_entry": closing.name,
		"opening_entry": entry.name,
		"settlement": settlement,
		"report": report,
	}


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def summarise(shift_name: str) -> dict:
	"""The day's report (FR-8.3).

	Read-only, and the single source for the screen, the printed report and the
	closing comparison — three tellings of one day must not differ.
	"""
	day = frappe.get_doc("Restaurant Shift", shift_name)
	validate_branch_access(day.branch)

	orders = frappe.get_all(
		"Restaurant Order",
		filters={"restaurant_shift": shift_name},
		fields=["name", "order_type", "status", "total_amount", "discount_amount", "sales_invoice"],
	)
	report = _report(day, orders, opening={})

	# What an open bill means here, so the screen can say the right thing about
	# it (`D-156`). A till that offers a way past a rule this branch does not
	# have — or hides the reason for one it does — is guessing on the cashier's
	# behalf. The screen only draws it; this decides it.
	still_open = report["orders"]["still_open"]

	report["must_finish_orders"] = _must_finish_orders(day.branch)
	report["blocked_by_open_orders"] = bool(still_open and report["must_finish_orders"])
	# **A warning, and never a refusal** (`D-158`). The day closes either way;
	# this only decides whether the screen mentions the pile it is carrying.
	report["carrying_too_many"] = _carrying_too_many(day.branch, still_open)
	report["carry_over_warning_at"] = _carry_over_warning_at(day.branch)

	# **Who is still on the clock, said before the day is closed** (`D-178`).
	# Closing it sends them home, and a manager should read that on the screen
	# they press the button on rather than discover it in a payroll report.
	from restaurant_pos.utils import attendance

	report["on_duty"] = len(attendance.on_duty_in(day.branch))
	return report


def summarise_till(opening_entry: str) -> dict:
	"""One drawer's takings (FR-8.3).

	**Attributed by cashier and time**, which is how ERPNext scopes a closing
	entry too: the orders this user settled on this terminal since the drawer was
	taken. An order carries no link to the session — it is created before anybody
	knows which drawer will settle it.

	A bill still open counts in no drawer, by design: it has taken no money, and
	it belongs to the floor until somebody settles it. The **day's** report is
	where an open bill is counted, and that is the report that refuses to close
	over one (`summarise`).
	"""
	entry = frappe.get_doc("POS Opening Entry", opening_entry)
	day = frappe.db.get_value(
		"Restaurant Shift",
		entry.get("rpos_restaurant_shift"),
		["name", "branch", "status", "opened_by", "opened_at", "closed_at"],
		as_dict=True,
	)

	# `summarise` above checks the branch and this did not, which let a cashier
	# restricted to one branch read another branch's takings by naming its
	# opening entry — and pop that branch's drawer, since `get_till_summary`
	# opens it as it answers (`D-093`). Taken from the profile rather than the
	# day, so it still holds when the entry predates the shift link.
	validate_branch_access(day.branch if day else _profile(entry.pos_profile).branch)

	# **What this drawer settled, not what was opened while it stood** (`D-188`).
	#
	# The docstring above has always said "settled" and the filter said
	# `opened_at`, which are the same thing only while one cashier opens and
	# closes every bill themselves. A bill opened at eleven and paid at three,
	# after the drawer changed hands, was **in no drawer's figures at all**: too
	# early for the one holding the notes, and its opener's drawer was counted
	# and closed hours before the money arrived.
	#
	# `cashier` is now whoever took the money, so the pair finally agree.
	filters = {
		"pos_profile": entry.pos_profile,
		"cashier": entry.user,
		"closed_at": (">=", entry.period_start_date),
	}
	if day:
		filters["restaurant_shift"] = day.name

	orders = frappe.get_all(
		"Restaurant Order",
		filters=filters,
		fields=["name", "order_type", "status", "total_amount", "discount_amount", "sales_invoice"],
	)

	opening = {row.mode_of_payment: flt(row.opening_amount) for row in entry.balance_details}
	report = _report(day or frappe._dict(name=None, branch=None, status=None), orders, opening)
	report["entry"] = entry.name
	report["user"] = entry.user
	report["opened_at"] = entry.period_start_date
	return report


def _report(day, orders: list, opening: dict) -> dict:
	closed = [row for row in orders if row.status == "closed"]
	sold = [row.sales_invoice for row in closed if row.sales_invoice]
	methods = _by_method(sold, opening)

	return {
		"shift": day.name,
		"branch": day.branch,
		"status": day.status,
		"orders": {
			"total": len(orders),
			"closed": len(closed),
			"cancelled": len([row for row in orders if row.status == "cancelled"]),
			"still_open": len([row for row in orders if row.status in OPEN_ORDER_STATUSES]),
		},
		"by_order_type": _by_order_type(closed),
		"by_method": methods,
		"voids": _void_count([row.name for row in closed]),
		"sales": money(sum(flt(row.total_amount) for row in closed)),
		# FR-8.3 — its own line, not netted off the takings: a shift that sold
		# 1000 and refunded 200 is a different day from one that sold 800.
		"returns": money(_returned_total(sold)),
		"discounts": money(sum(flt(row.discount_amount) for row in closed)),
		# D-029 — what the drawer should hold, credit deliberately absent.
		"till_expected": money(sum(row["expected"] for row in methods if row["kind"] == "till")),
		"credit_total": money(sum(row["sales"] for row in methods if row["kind"] == "credit")),
	}


def _credit_notes(invoices: list[str]) -> list[str]:
	"""Submitted returns raised against these invoices (FR-9, D-064)."""
	if not invoices:
		return []

	return frappe.get_all(
		"Sales Invoice",
		filters={"return_against": ("in", invoices), "docstatus": 1},
		pluck="name",
	)


def _returned_total(invoices: list[str]) -> float:
	"""What went back to customers, as a positive figure (FR-8.3)."""
	notes = _credit_notes(invoices)
	if not notes:
		return 0.0

	return abs(
		sum(
			flt(row.grand_total)
			for row in frappe.get_all(
				"Sales Invoice", filters={"name": ("in", notes)}, fields=["grand_total"]
			)
		)
	)


def _by_order_type(closed: list) -> list[dict]:
	"""FR-8.3 — how the takings split between dine in, takeaway and the platforms."""
	tally: dict[str, dict] = {}
	for row in closed:
		entry = tally.setdefault(row.order_type, {"order_type": row.order_type, "count": 0, "sales": 0.0})
		entry["count"] += 1
		entry["sales"] += flt(row.total_amount)

	for entry in tally.values():
		entry["sales"] = money(entry["sales"])
		entry["title_ar"] = frappe.db.get_value("Restaurant Order Type", entry["order_type"], "title_ar")

	return sorted(tally.values(), key=lambda entry: -entry["sales"])


def _by_method(invoices: list[str], opening: dict) -> list[dict]:
	"""FR-8.3 — takings per payment method, and what each one means.

	Read from the **Sales Invoice**, which is where a payment is recorded: the
	order carries no payment rows of its own (D-022). One query for the whole
	period rather than one per order — a busy day is three hundred invoices.

	``kind`` is the point: ``till`` is money to count, ``credit`` is money owed
	by a platform or a company. Listing both and totalling them apart is what
	keeps the variance figure honest (D-029).

	**Only submitted invoices count** (D-062). Cancelling an invoice from the
	ERPNext desk reverses the ledger but leaves its payment rows in the table
	with the parent's `docstatus = 2` — so the drawer was still being told to
	expect money the books had already given back. Measured, not assumed: the
	expected figure did not move when a paid invoice was cancelled.
	"""
	live = (
		frappe.get_all("Sales Invoice", filters={"name": ("in", invoices), "docstatus": 1}, pluck="name")
		if invoices
		else []
	)

	# FR-9 — and the credit notes raised against them (D-064). A refund carries
	# negative payment rows, so counting them alongside the sales is what takes
	# the money back out of the expected drawer. Without this the till would
	# still be asked for cash the cashier handed to a customer.
	live += _credit_notes(live)

	rows = (
		frappe.get_all(
			"Sales Invoice Payment",
			filters={"parent": ("in", live), "parenttype": "Sales Invoice"},
			fields=["mode_of_payment", "amount"],
		)
		if live
		else []
	)

	tally: dict[str, dict] = {}
	for row in rows:
		method = row.mode_of_payment
		entry = tally.setdefault(
			method,
			{"method": method, "kind": "credit" if is_credit_method(method) else "till", "sales": 0.0},
		)
		entry["sales"] += flt(row.amount)

	# A float went into a drawer even if nothing was sold through that method.
	for method, amount in opening.items():
		entry = tally.setdefault(
			method,
			{"method": method, "kind": "credit" if is_credit_method(method) else "till", "sales": 0.0},
		)
		entry["opening"] = flt(amount)

	for entry in tally.values():
		entry.setdefault("opening", 0.0)
		entry["sales"] = money(entry["sales"])
		entry["opening"] = money(entry["opening"])
		# Nothing is expected in a drawer for credit: the money is not there.
		entry["expected"] = 0.0 if entry["kind"] == "credit" else money(entry["opening"] + entry["sales"])

	return sorted(tally.values(), key=lambda entry: (entry["kind"], -entry["sales"]))


def _void_count(order_names: list[str]) -> int:
	if not order_names:
		return 0

	return len(
		frappe.get_all(
			"Restaurant Order Item",
			filters={"parent": ("in", order_names), "parenttype": "Restaurant Order", "status": "void"},
		)
	)


def _reconcile(report: dict, counted: dict | None, *, wants_count: bool) -> dict:
	"""Expected against counted, for the drawer only (BR-042, D-029).

	When the branch does not ask for a count, the expected figure stands as the
	counted one and the variance is zero — a shop that does not count has no
	difference to explain, and inventing one would put a mandatory reason box in
	front of a cashier for a number nobody measured.
	"""
	counted = counted or {}

	lines = []
	total_expected = 0.0
	total_counted = 0.0

	for row in report["by_method"]:
		if row["kind"] == "credit":
			# Reported, never reconciled: the money was never in the drawer.
			lines.append({**row, "counted": None, "variance": None})
			continue

		expected = flt(row["expected"])
		actual = money(counted.get(row["method"], expected)) if wants_count else expected
		total_expected += expected
		total_counted += actual
		lines.append({**row, "counted": actual, "variance": money(actual - expected)})

	return {
		"settlement_required": wants_count,
		"methods": lines,
		"expected": money(total_expected),
		"counted": money(total_counted),
		"variance": money(total_counted - total_expected),
		"credit_total": report["credit_total"],
	}


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _clean_floats(opening_floats: dict | None) -> dict:
	"""Only real methods, only real amounts.

	A float typed against a credit method would inflate an expected drawer that
	holds nothing.
	"""
	cleaned = {}
	for method, amount in (opening_floats or {}).items():
		if not frappe.db.exists("Mode of Payment", method):
			frappe.throw(_("Payment method {0} does not exist.").format(method))
		if is_credit_method(method):
			continue
		if flt(amount):
			cleaned[method] = money(amount)

	return cleaned


def _default_method(pos_profile: str) -> str:
	row = frappe.get_all(
		"POS Payment Method",
		filters={"parent": pos_profile, "parenttype": "POS Profile"},
		fields=["mode_of_payment"],
		order_by="`default` desc, idx asc",
		limit=1,
	)
	if row:
		return row[0].mode_of_payment

	frappe.throw(_("POS Profile {0} has no payment method configured.").format(pos_profile))


def _point_terminal_at(pos_profile: str, shift: str) -> None:
	frappe.db.set_value("POS Profile", pos_profile, "restaurant_shift", shift, update_modified=False)


def _profile(pos_profile: str) -> frappe._dict:
	profile = frappe.db.get_value(
		"POS Profile",
		pos_profile,
		["name", "restaurant_section", "restaurant_shift", "company"],
		as_dict=True,
	)
	if not profile:
		frappe.throw(_("POS Profile {0} does not exist.").format(pos_profile))

	profile.branch = table_section_branch(profile.restaurant_section)
	if not profile.branch:
		frappe.throw(_("POS Profile {0} has no Restaurant Section configured.").format(pos_profile))

	branch = frappe.db.get_value(
		"Branch", profile.branch, ["shift_type", "settlement_required"], as_dict=True
	)
	profile.branch_shift_type = (branch or {}).get("shift_type") or "single"
	profile.settlement_required = cint((branch or {}).get("settlement_required"))
	return profile


def _open_day(profile) -> frappe._dict | None:
	"""The day this terminal sells under.

	Its own if it still points at an open one; otherwise the branch's, which is
	what lets a second terminal join the morning's day without opening a rival.
	"""
	if profile.restaurant_shift:
		current = frappe.db.get_value(
			"Restaurant Shift",
			profile.restaurant_shift,
			["name", "title", "status", "opened_by", "opened_at", "branch"],
			as_dict=True,
		)
		if current and current.status == "open":
			return current

	return frappe.db.get_value(
		"Restaurant Shift",
		{"branch": profile.branch, "status": "open"},
		["name", "title", "status", "opened_by", "opened_at", "branch"],
		as_dict=True,
	)


#: What the screen and the selling gate both need to know about a drawer.
TILL_FIELDS = ["name", "user", "period_start_date"]


def _my_till(profile) -> frappe._dict | None:
	return frappe.db.get_value(
		"POS Opening Entry",
		{"pos_profile": profile.name, "user": frappe.session.user, "status": "Open", "docstatus": 1},
		TILL_FIELDS,
		as_dict=True,
	)


def held_till(user: str) -> str | None:
	"""The drawer this person still has open, on **any** terminal (`D-177`).

	Deliberately not scoped to a POS Profile, unlike `_my_till`. That one answers
	"may this terminal sell"; this one answers "may this person go home", and a
	drawer left open on the till at the other end of the counter is still theirs
	to count. Scoping it would let a cashier clock out by walking to a different
	screen.
	"""
	return frappe.db.get_value(
		"POS Opening Entry",
		{"user": user, "status": "Open", "docstatus": 1},
		"name",
	)


def _any_till(profile) -> frappe._dict | None:
	return frappe.db.get_value(
		"POS Opening Entry",
		{"pos_profile": profile.name, "status": "Open", "docstatus": 1},
		TILL_FIELDS,
		as_dict=True,
	)


def _open_till(profile) -> frappe._dict | None:
	"""The drawer open on this terminal — this user's first, then anyone's.

	A ``single`` branch shares one drawer, so the second cashier finds the one
	already open rather than a locked screen.
	"""
	return _my_till(profile) or _any_till(profile)


def selling_till(pos_profile: str) -> frappe._dict | None:
	"""The drawer this cashier's sales would land in, if there is one (BR-044).

	**A day is not enough.** Closing a till hands the drawer back and counts it;
	the day stays open for whoever comes next. A sale rung up after that count
	belongs to no drawer at all — it shows in the day's takings and in nobody's
	close, which is the one place a shortage is meant to be traceable to a
	person.

	``single`` shares one drawer, so whichever is open on the terminal is the
	answer. ``multi`` gives each cashier their own, and selling into somebody
	else's is how a difference lands on the wrong name.
	"""
	profile = _profile(pos_profile)
	return _open_till(profile) if profile.branch_shift_type == "single" else _my_till(profile)


def may_sell(pos_profile: str) -> bool:
	"""BR-044 — may this terminal ring money **right now** (D-054, D-055).

	Both halves: the branch's day, and a drawer this cashier's takings land in.

	This is the whole rule, in one place, asked by everything that moves money —
	the endpoints, and the session payload the screens gate on. A second copy of
	it anywhere is a copy that will disagree with the endpoint that refuses.
	"""
	profile = _profile(pos_profile)

	day = profile.restaurant_shift
	if not (day and frappe.db.get_value("Restaurant Shift", day, "status") == "open"):
		return False

	return bool(_open_till(profile) if profile.branch_shift_type == "single" else _my_till(profile))


def assert_may_sell(pos_profile: str) -> None:
	"""Refuse anything that moves money while no shift is open (BR-044).

	Selling, paying, refunding — a closed drawer means the takings have been
	counted and handed over, so anything after it lands in no count at all.
	"""
	if not may_sell(pos_profile):
		frappe.throw(_("Open a shift before taking orders."))


def _must_finish_orders(branch: str) -> bool:
	"""Whether this branch ends its day with nothing left open (`D-105`).

	Defaults to on for a branch created before the setting existed: refusing to
	close is recoverable in one step, and a day closed over bills nobody meant
	to carry is not.
	"""
	setting = frappe.db.get_value("Branch", branch, "close_open_orders_with_day")
	return True if setting is None else bool(setting)


#: When to mention the pile, for a branch that has not said (`D-158`). Chosen
#: from the measurement, not from taste: a till reading 1,155 open bills draws
#: its list in 0.6s and one reading 3,155 takes 4.3s — and it redraws on every
#: order in the branch. A hundred is comfortably inside the flat part of that
#: curve, so the warning arrives long before anybody feels it.
DEFAULT_CARRY_OVER_WARNING = 100


def _carry_over_warning_at(branch: str) -> int:
	"""How many carried bills this branch wants to hear about. ``0`` is never."""
	setting = frappe.db.get_value("Branch", branch, "carried_orders_warning_at")
	return DEFAULT_CARRY_OVER_WARNING if setting is None else cint(setting)


def _carrying_too_many(branch: str, still_open: int) -> bool:
	"""Whether the pile this branch is carrying is worth saying out loud.

	**A number to watch, not a door to lock** (`D-158`). *"Carry over"* was
	written to mean *"a tab may run past midnight"* (`D-105`), and with nothing
	else forcing a bill closed it comes to mean *"for ever"*: three bills
	abandoned a night is a thousand in a year, and the floor is deliberately
	unbounded by date (`D-146`) so the till reads every one of them on every
	refresh.

	A ceiling stood here for an hour, refusing to close the day above it, and it
	was the wrong shape: **ending the business day is an accounting act, and a
	long list is a technical complaint.** Stopping the first for the second would
	strand a manager at two in the morning over something recoverable at any
	time — our fault, and worse than the four seconds it would have saved.

	So the till says the number, every close, and the person who can act on it is
	the person who reads it.
	"""
	if _must_finish_orders(branch):
		return False

	warn_at = _carry_over_warning_at(branch)
	return bool(warn_at) and still_open > warn_at


def _tills_of(shift_name: str, *, status: str) -> list[str]:
	return frappe.get_all(
		"POS Opening Entry",
		filters={"rpos_restaurant_shift": shift_name, "status": status, "docstatus": 1},
		pluck="name",
	)

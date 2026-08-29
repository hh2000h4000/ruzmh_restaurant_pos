# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Opening and closing a shift (FR-8.1..8.3, BR-040..045).

Nothing sells without one: ``utils/order._open_shift_for`` refuses every order
whose terminal is not pointed at an open ``Restaurant Shift`` (BR-044). Until
now the only way to open one was by hand in the desk, which meant a restaurant
could not start its day from the till it works on.

**The count and the credit.** A shift is reconciled against what is *in the
drawer*. A delivery platform has already taken the customer's money and a
corporate account will pay on a statement — neither puts a riyal in the till
(``DECISIONS.md`` D-029). Counting them into the expected cash would show a
shortfall the size of the day's app orders, every single day, and teach the
cashier that the variance figure means nothing. So credit methods are reported
and **excluded from the reconciliation**.

Refs: FR-8.1, FR-8.2, FR-8.3, BR-040..BR-045, D-029
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime, nowdate

from restaurant_pos.utils.payment import is_credit_method
from restaurant_pos.utils.permissions import assert_permission, validate_branch_access
from restaurant_pos.utils.totals import money

#: An order still on the floor. Closing over one strands a bill nobody can pay.
OPEN_ORDER_STATUSES = ("draft", "active", "in_kitchen", "pending_payment")


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #


def shift_state(pos_profile: str) -> dict:
	"""What the till needs to know before it can sell (FR-8.1).

	Answers three questions in one call, because the screen asks all three at
	once: is a shift open, is it mine, and may I close it.
	"""
	profile = _profile(pos_profile)
	validate_branch_access(profile.branch)

	shift = _open_shift(profile)
	if not shift:
		return {"open": False, "branch": profile.branch, "shift_type": profile.branch_shift_type}

	return {
		"open": True,
		"branch": profile.branch,
		"shift_type": profile.branch_shift_type,
		"shift": shift.name,
		"title": shift.title,
		"opened_by": shift.opened_by,
		"opened_by_name": frappe.db.get_value("User", shift.opened_by, "full_name"),
		"opened_at": shift.opened_at,
		"is_mine": shift.opened_by == frappe.session.user,
		"settlement_required": bool(profile.settlement_required),
	}


def summarise(shift_name: str) -> dict:
	"""The shift report (FR-8.3), and what closing it will be measured against.

	Read-only: the same figures back a screen, a printed report and the closing
	comparison, so the three can never tell different stories.
	"""
	shift = frappe.get_doc("Restaurant Shift", shift_name)
	validate_branch_access(shift.branch)

	orders = frappe.get_all(
		"Restaurant Order",
		filters={"restaurant_shift": shift_name},
		fields=["name", "order_type", "status", "total_amount", "discount_amount", "sales_invoice"],
	)

	closed = [row for row in orders if row.status == "closed"]
	names = [row.name for row in closed]

	opening = _opening_floats(shift)
	methods = _by_method([row.sales_invoice for row in closed if row.sales_invoice], opening)

	return {
		"shift": shift.name,
		"branch": shift.branch,
		"status": shift.status,
		"opened_by": shift.opened_by,
		"opened_at": shift.opened_at,
		"closed_at": shift.closed_at,
		"orders": {
			"total": len(orders),
			"closed": len(closed),
			"cancelled": len([row for row in orders if row.status == "cancelled"]),
			"still_open": len([row for row in orders if row.status in OPEN_ORDER_STATUSES]),
		},
		"by_order_type": _by_order_type(closed),
		"by_method": methods,
		"voids": _void_count(names),
		"sales": money(sum(flt(row.total_amount) for row in closed)),
		"discounts": money(sum(flt(row.discount_amount) for row in closed)),
		# D-029 — what the drawer should hold, credit deliberately absent.
		"till_expected": money(sum(row["expected"] for row in methods if row["kind"] == "till")),
		"credit_total": money(sum(row["sales"] for row in methods if row["kind"] == "credit")),
	}


def _by_order_type(closed: list) -> list[dict]:
	"""FR-8.3 — how the day split between dine in, takeaway and the platforms."""
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
	order carries no payment rows of its own (D-022). One query for the shift
	rather than one per order — a busy day is three hundred invoices.

	``kind`` is the whole point: ``till`` is money to count, ``credit`` is money
	owed by a platform or a company. Reporting them in one list and totalling
	them separately is what keeps the variance figure honest (D-029).
	"""
	rows = (
		frappe.get_all(
			"Sales Invoice Payment",
			filters={"parent": ("in", invoices), "parenttype": "Sales Invoice"},
			fields=["mode_of_payment", "amount"],
		)
		if invoices
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

	# A float was put in a drawer even if nothing was sold through it.
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


def _opening_floats(shift) -> dict:
	data = frappe.parse_json(shift.settlement_data) if shift.settlement_data else {}
	return data.get("opening") or {}


# --------------------------------------------------------------------------- #
# Opening
# --------------------------------------------------------------------------- #


def open_shift(*, pos_profile: str, opening_floats: dict | None = None, title: str | None = None) -> dict:
	"""Start selling (FR-8.1, BR-040).

	**Single-shift branches join rather than multiply.** BR-041 says one shift
	covers the day and several cashiers work under it; creating a second would
	split one day's takings across two reports that neither balances.
	"""
	assert_permission("can_open_shift")

	profile = _profile(pos_profile)
	validate_branch_access(profile.branch)

	existing = _open_shift(profile)
	if existing:
		if profile.branch_shift_type == "multi" and existing.opened_by != frappe.session.user:
			frappe.throw(
				_("{0} has a shift open on this branch. Close it before opening another.").format(
					frappe.db.get_value("User", existing.opened_by, "full_name") or existing.opened_by
				)
			)

		_point_terminal_at(pos_profile, existing.name)
		return {"shift": existing.name, "joined": True}

	shift = frappe.get_doc(
		{
			"doctype": "Restaurant Shift",
			"title": title or _("Shift {0}").format(nowdate()),
			"branch": profile.branch,
			"shift_date": nowdate(),
			"shift_type": "full_day",
			"status": "open",
			"opened_by": frappe.session.user,
			"opened_at": now_datetime(),
			# FR-8.1 step 3 — what was in each drawer before a riyal was taken.
			"settlement_data": frappe.as_json({"opening": _clean_floats(opening_floats)}),
		}
	)
	shift.insert(ignore_permissions=True)

	_point_terminal_at(pos_profile, shift.name)
	return {"shift": shift.name, "joined": False}


def _clean_floats(opening_floats: dict | None) -> dict:
	"""Only real methods, only real amounts.

	A float typed against a credit method would be counted into an expected
	drawer that has nothing in it.
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


def _point_terminal_at(pos_profile: str, shift: str) -> None:
	frappe.db.set_value("POS Profile", pos_profile, "restaurant_shift", shift, update_modified=False)


# --------------------------------------------------------------------------- #
# Closing
# --------------------------------------------------------------------------- #


def close_shift(
	*,
	shift_name: str,
	counted: dict | None = None,
	variance_reason: str | None = None,
	force: bool = False,
) -> dict:
	"""Finish the day and reconcile the drawer (FR-8.2, BR-042, BR-043, BR-045).

	Refuses over an order still on the floor unless ``force``: closing across
	one strands a bill in a report that says the day is done. The screen shows
	the count and lets a manager decide.
	"""
	shift = frappe.get_doc("Restaurant Shift", shift_name)
	validate_branch_access(shift.branch)

	if shift.status == "closed":
		frappe.throw(_("Shift {0} is already closed.").format(shift_name))

	assert_permission("can_close_shift")
	# BR-045 — somebody else's day is not yours to end.
	if shift.opened_by != frappe.session.user:
		assert_permission("can_close_others_shift")

	report = summarise(shift_name)
	if report["orders"]["still_open"] and not force:
		frappe.throw(
			_("{0} orders are still open on this shift.").format(report["orders"]["still_open"]),
			frappe.ValidationError,
		)

	settlement = _reconcile(shift, report, counted)

	if settlement["variance"] and not (variance_reason or "").strip():
		frappe.throw(_("Enter a reason for the difference before closing."))

	shift.status = "closed"
	shift.closed_by = frappe.session.user
	shift.closed_at = now_datetime()
	shift.total_sales = report["sales"]
	shift.total_orders = report["orders"]["closed"]
	shift.total_voids = report["voids"]
	shift.variance_reason = (variance_reason or "").strip() or None
	shift.settlement_data = frappe.as_json(
		{"opening": _opening_floats(shift), "report": report, "settlement": settlement}
	)
	shift.save(ignore_permissions=True)

	# The terminal stops selling the moment its shift ends (BR-044).
	for profile in frappe.get_all("POS Profile", filters={"restaurant_shift": shift_name}, pluck="name"):
		frappe.db.set_value("POS Profile", profile, "restaurant_shift", None, update_modified=False)

	return {"shift": shift.name, "settlement": settlement, "report": report}


def _reconcile(shift, report: dict, counted: dict | None) -> dict:
	"""Expected against counted, for the drawer only (BR-042, D-029).

	When the branch does not ask for a count, the expected figure stands as the
	counted one and the variance is zero — a shop that does not count has no
	difference to explain, and inventing one would put a reason box in front of
	a cashier for a number nobody measured.
	"""
	wants_count = bool(frappe.db.get_value("Branch", shift.branch, "settlement_required"))
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


def _profile(pos_profile: str) -> frappe._dict:
	profile = frappe.db.get_value(
		"POS Profile", pos_profile, ["name", "restaurant_section", "restaurant_shift"], as_dict=True
	)
	if not profile:
		frappe.throw(_("POS Profile {0} does not exist.").format(pos_profile))

	profile.branch = (
		frappe.db.get_value("Restaurant Section", profile.restaurant_section, "branch")
		if profile.restaurant_section
		else None
	)
	if not profile.branch:
		frappe.throw(_("POS Profile {0} has no Restaurant Section configured.").format(pos_profile))

	branch = frappe.db.get_value(
		"Branch", profile.branch, ["shift_type", "settlement_required"], as_dict=True
	)
	profile.branch_shift_type = (branch or {}).get("shift_type") or "single"
	profile.settlement_required = cint((branch or {}).get("settlement_required"))
	return profile


def _open_shift(profile) -> frappe._dict | None:
	"""The shift this terminal would sell under.

	Its own if it still points at an open one; otherwise the branch's, which is
	what lets a second till join a single-shift day without opening a rival.
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

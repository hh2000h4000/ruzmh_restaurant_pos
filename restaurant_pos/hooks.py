from . import __version__ as app_version

app_name = "restaurant_pos"
app_title = "Restaurant POS"
app_publisher = "RPOS"
app_description = "Restaurant POS (RPOS) built natively on Frappe / ERPNext v15"
app_email = "hh2000h4000@gmail.com"
app_license = "MIT"

# The app extends ERPNext masters (Item, Item Group, POS Profile, Branch, POS Profile).
#
# **hrms is not optional** (`D-135`). Attendance records punches in
# `Employee Checkin`, which ships there — and the dependency went undeclared for
# weeks while `frappe.db.get_value` answered `None` on the absent table instead
# of raising. The feature looked present and would have failed under the first
# member of staff who pressed it. Declared here so a fresh site cannot repeat
# it: `install-app` refuses rather than installing something half-wired.
required_apps = ["frappe/erpnext", "frappe/hrms"]

# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------
after_install = "restaurant_pos.setup.install.after_install"

# The suite builds the restaurant it needs rather than borrowing a site's own
# data, so it can run on a throwaway site and leave the demo alone (D-041).
before_tests = "restaurant_pos.setup.test_fixtures.before_tests"
after_migrate = "restaurant_pos.setup.install.after_migrate"

# ---------------------------------------------------------------------------
# Document events
# ---------------------------------------------------------------------------
# The manager PIN is a Password custom field on User. Frappe would persist it
# reversibly and check_password() would never see it, so it is intercepted and
# stored as a one-way hash instead (DECISIONS.md D-015, D-016).
doc_events = {
	# D-201 — and an RPOS role is granted on this form, so the escalation guard
	# (FR-12.6) runs here rather than only inside an API nothing called.
	"User": {
		"validate": [
			"restaurant_pos.utils.manager_pin.hold_pin_aside",
			"restaurant_pos.utils.permissions.guard_user_changes",
		],
		"on_update": [
			"restaurant_pos.utils.manager_pin.store_pin_hashed",
			"restaurant_pos.utils.permissions.log_user_changes",
		],
	},
	# D-063 — a point-of-sale sale is reversed by a return, never by cancelling
	# the invoice. Cancelling from the desk left the ledger reversed and the
	# order still saying `closed`, with nobody told (D-062).
	#
	# D-189 — and ERPNext's own loyalty stays off an RPOS invoice. It fetches the
	# customer's program onto every invoice and grants its own points on submit,
	# which doubled every balance beside the ledger rows RPOS writes.
	"Sales Invoice": {
		"before_cancel": "restaurant_pos.utils.payment.block_invoice_cancel",
		"validate": "restaurant_pos.utils.loyalty.keep_erpnext_out",
	},
	# D-189 — a program RPOS cannot honour is refused when it is saved: tiers
	# (ERPNext's pick the wrong one) and an empty expiry (points die tonight).
	"Loyalty Program": {"validate": "restaurant_pos.utils.loyalty.validate_program"},
}

# D-085 — a print job carries the bitmap it printed, about 15 KB of base64 each.
# Nothing else in the app grows per-receipt like this, and a queue table nobody
# prunes is a disk that fills on a Friday night.
scheduler_events = {
	"daily": [
		"restaurant_pos.utils.printing.prune_jobs",
		# D-106 — a dozen rows per bill is millions a year. The order is kept for
		# ever; a year-old "quantity changed from 1 to 2" answers nothing.
		"restaurant_pos.utils.activity.prune_default",
		# D-206 — a row per write, online or not. Kept thirty days: well past any
		# replay that can still land (`idempotency.KEEP_DAYS` says why).
		"restaurant_pos.utils.idempotency.prune",
	],
}

# D-090 — `{{ field | rtl }}` in the print templates. The renderer that turns a
# receipt into a bitmap cannot lay Arabic out beside digits without help, and
# the help has to be conditional; `printing.rtl` explains what was measured.
jinja = {
	"filters": [
		"restaurant_pos.utils.printing.rtl",
	],
	# **So a print format can draw the QR.** The till's receipt gets it from
	# `receipt_context`; a copy printed from the desk — the one an auditor is
	# handed — had no way to reach it at all, and came out without one
	# (`D-153`).
	"methods": [
		"restaurant_pos.utils.zatca.rpos_invoice_qr",
	],
}

# D-096 — where a POS role lands after any Frappe login.
#
# The app is the whole job for these roles, and the desk is a place a cashier
# has no business in and no idea what to do with. It matters because Frappe's
# own logout answers with `home_page: "/login"`: somebody who arrives there and
# signs in should come back to a till, not to an accounting workspace.
role_home_page = {
	"POS Cashier": "restaurant-pos",
	"POS Senior Cashier": "restaurant-pos",
	"POS Manager": "restaurant-pos",
}

# ---------------------------------------------------------------------------
# The cashier PWA
# ---------------------------------------------------------------------------
# The Vue app owns every path under /restaurant-pos and routes them itself, so
# a deep link or a refresh has to reach the same page rather than a 404.
website_route_rules = [
	{"from_route": "/restaurant-pos/<path:app_path>", "to_route": "restaurant-pos"},
]

# The page is generated by `yarn build` from Vite's index.html, because the
# asset filenames are content-hashed (see frontend/vite.config.ts).

# ---------------------------------------------------------------------------
# Phase 2+ hooks are intentionally left unregistered until the corresponding
# phase is implemented (see docs/10_Implementation_Plan.md).
#
#   app_include_js        -> Phase 4 (desk-side helpers)
#   fixtures              -> handled by setup/defaults.py instead (D-013)
# ---------------------------------------------------------------------------

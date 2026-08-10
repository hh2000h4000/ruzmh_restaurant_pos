from . import __version__ as app_version

app_name = "restaurant_pos"
app_title = "Restaurant POS"
app_publisher = "RPOS"
app_description = "Restaurant POS (RPOS) built natively on Frappe / ERPNext v15"
app_email = "hh2000h4000@gmail.com"
app_license = "MIT"

# The app extends ERPNext masters (Item, Item Group, POS Profile, Branch, POS Profile).
required_apps = ["frappe/erpnext"]

# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------
after_install = "restaurant_pos.setup.install.after_install"
after_migrate = "restaurant_pos.setup.install.after_migrate"

# ---------------------------------------------------------------------------
# Document events
# ---------------------------------------------------------------------------
# The manager PIN is a Password custom field on User. Frappe would persist it
# reversibly and check_password() would never see it, so it is intercepted and
# stored as a one-way hash instead (DECISIONS.md D-015, D-016).
doc_events = {
	"User": {
		"validate": "restaurant_pos.restaurant_pos.utils.manager_pin.hold_pin_aside",
		"on_update": "restaurant_pos.restaurant_pos.utils.manager_pin.store_pin_hashed",
	}
}

# ---------------------------------------------------------------------------
# Phase 2+ hooks are intentionally left unregistered until the corresponding
# phase is implemented (see docs/10_Implementation_Plan.md).
#
#   doc_events            -> Phase 2 (order lifecycle side effects)
#   scheduler_events      -> Phase 2 (offline queue reconciliation)
#   website_route_rules   -> Phase 2 (Vue 3 PWA entry point)
#   app_include_js        -> Phase 2 (desk-side helpers)
#   fixtures              -> Phase 1 task 3 (default data)
# ---------------------------------------------------------------------------

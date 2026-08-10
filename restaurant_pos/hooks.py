from . import __version__ as app_version  # noqa: F401

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
# Phase 2+ hooks are intentionally left unregistered until the corresponding
# phase is implemented (see docs/10_Implementation_Plan.md).
#
#   doc_events            -> Phase 2 (order lifecycle side effects)
#   scheduler_events      -> Phase 2 (offline queue reconciliation)
#   website_route_rules   -> Phase 2 (Vue 3 PWA entry point)
#   app_include_js        -> Phase 2 (desk-side helpers)
#   fixtures              -> Phase 1 task 3 (default data)
# ---------------------------------------------------------------------------

# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""Install-time setup for the Restaurant POS app.

Phase 1 responsibility: extend the ERPNext masters listed in
``docs/05_Database_Design.md`` section 18 with the fields RPOS needs.

Per ``docs/04_System_Architecture.md`` section 9, ERPNext core is never
modified - every extension is a ``Custom Field``.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from restaurant_pos.setup import (
	cash_accounts,
	desk_tiles,
	gift_card_accounts,
	over_short_account,
	platform_accounts,
	waste_account,
)
from restaurant_pos.setup.defaults import create_default_data
from restaurant_pos.setup.print_templates import create_default_templates
from restaurant_pos.utils.sale_doc import LINE_COST, POSTED_ENTRY, SALE, SALE_ITEM, WASTED


# ``Restaurant Branch`` in the database design is the ERPNext ``Branch`` DocType
# extended with restaurant configuration (see 10_Implementation_Plan.md, Phase 1).
def _made_by_a_batch(after: str) -> dict:
	return {
		"fieldname": "rpos_posting_batch",
		"fieldtype": "Link",
		"options": "POS Posting Batch",
		"label": "RPOS Posting Batch",
		"read_only": 1,
		"no_copy": 1,
		"description": "The batch of till sales this document posts.",
		"insert_after": after,
	}


CUSTOM_FIELDS = {
	# The till session is ERPNext's own POS Opening Entry (D-047); all it lacks
	# is which business day it was taken in, because ERPNext has no such thing.
	"POS Opening Entry": [
		{
			"fieldname": "rpos_restaurant_shift",
			"fieldtype": "Link",
			"options": "Restaurant Shift",
			"label": "Business Day",
			"read_only": 1,
			"insert_after": "pos_profile",
		},
	],
	# **A punch the system made, marked as one** (`D-178`).
	#
	# Closing the business day sends home whoever forgot to clock out, and the
	# time on that punch is the day's close — a reasonable figure, not a fact.
	# Payroll reads `Employee Checkin`, so the mark has to be *on the row*: an
	# entry indistinguishable from a real punch is an hour nobody can question.
	# Toast does exactly this and lets a manager list them and correct the time.
	"Employee Checkin": [
		{
			"fieldname": "rpos_auto_clock_out",
			"fieldtype": "Check",
			"label": "Automatic Clock Out",
			"read_only": 1,
			"in_list_view": 1,
			"description": "Written when the restaurant's business day was closed, not punched by the employee.",
			"insert_after": "skip_auto_attendance",
		},
	],
	# BR-043 — a difference has to be answered for, and ERPNext's closing entry
	# has nowhere to write the answer.
	"POS Closing Entry": [
		{
			"fieldname": "rpos_variance_reason",
			"fieldtype": "Small Text",
			"label": "Variance Reason",
			"insert_after": "user",
		},
		# `D-357` — the entry the accountant booked the difference in, so it is
		# never booked twice and the report can say which are done.
		{
			"fieldname": "rpos_difference_entry",
			"fieldtype": "Link",
			"options": "Journal Entry",
			"label": "Difference Entry",
			"insert_after": "rpos_variance_reason",
			"read_only": 1,
			"no_copy": 1,
			"allow_on_submit": 1,
		},
	],
	"Branch": [
		{
			"fieldname": "rpos_settings_section",
			"fieldtype": "Section Break",
			"label": "Restaurant Settings",
			"insert_after": "branch",
		},
		{
			"fieldname": "company",
			"fieldtype": "Link",
			"options": "Company",
			"label": "Company",
			"reqd": 1,
			"insert_after": "rpos_settings_section",
		},
		{
			"fieldname": "manager",
			"fieldtype": "Link",
			"options": "User",
			"label": "Manager",
			"insert_after": "company",
		},
		{
			"fieldname": "phone",
			"fieldtype": "Data",
			"options": "Phone",
			"label": "Phone",
			"insert_after": "manager",
		},
		{
			"fieldname": "vat_number",
			"fieldtype": "Data",
			"label": "VAT Number",
			"description": "Printed on customer receipts.",
			"insert_after": "phone",
		},
		# **The first part of every invoice number of this branch** (`D-309`):
		# branch, terminal, count. Data rather than Int, so a number somebody
		# chose is kept as they wrote it.
		{
			"fieldname": "rpos_branch_number",
			"fieldtype": "Data",
			"label": "Branch Number",
			"no_copy": 1,
			"description": "Starts every invoice number of this branch, e.g. 1002-01-000001. Leave empty and the next free number is taken. It cannot change once the branch has invoices.",
			"insert_after": "vat_number",
		},
		{
			"fieldname": "rpos_settings_cb",
			"fieldtype": "Column Break",
			"insert_after": "rpos_branch_number",
		},
		{
			"fieldname": "default_cost_center",
			"fieldtype": "Link",
			"options": "Cost Center",
			"label": "Default Cost Center",
			"reqd": 1,
			"insert_after": "rpos_settings_cb",
		},
		{
			"fieldname": "shift_type",
			"fieldtype": "Select",
			"options": "single\nmulti",
			"default": "single",
			# D-218 — named for what it decides: who a drawer belongs to. "Shift
			# Type" with "single" read as "one shift all day", and the user set a
			# branch to "multi" wanting two shifts a day — which "single" does.
			"label": "Drawer Type",
			"description": (
				"Shared: one drawer open at a time on the terminal, and whoever signs in works on it. "
				"Close it at the change of shift and the next cashier opens a new one the same day. "
				"Per cashier: several drawers open at once, one for each cashier."
			),
			"reqd": 1,
			"insert_after": "default_cost_center",
		},
		{
			"fieldname": "order_number_reset",
			"fieldtype": "Select",
			"options": "daily\nshift\nweekly\nmonthly\nnever",
			"default": "daily",
			"label": "Order Number Resets",
			"description": (
				"How often the short number a customer is told goes back to 1. "
				"Daily is what most restaurants use; the record id is unaffected "
				"and stays unique forever (FR-2.10)."
			),
			"insert_after": "shift_type",
		},
		{
			"fieldname": "settlement_required",
			"fieldtype": "Check",
			"label": "Settlement Required",
			"insert_after": "order_number_reset",
		},
		{
			# D-105 — the restaurant decides what an open bill means at midnight.
			"fieldname": "close_open_orders_with_day",
			"fieldtype": "Check",
			"default": "1",
			"label": "Finish open orders before closing the day",
			"description": (
				"On: the day cannot end while a bill is still open, so every one of them is "
				"settled or cancelled first. Off: open bills carry over to the next day and "
				"stay fully editable. Neither is wrong — a table that leaves without paying "
				"is an ordinary evening in some restaurants and an incident in others."
			),
			"insert_after": "settlement_required",
		},
		{
			# D-158 — a number to watch, not a door to lock.
			"fieldname": "carried_orders_warning_at",
			"fieldtype": "Int",
			"default": "100",
			"label": "Warn when this many orders are carried over",
			"description": (
				"Only applies where the setting above is off. Closing the day says so when "
				"more than this many bills are still open — it never refuses: ending the "
				"business day is an accounting act, and stopping one because a list has grown "
				"is the wrong kind of answer. Measured, a till reading three thousand open "
				"bills takes four seconds to draw its own list, and it redraws on every order "
				"in the branch. 0 means never warn."
			),
			"insert_after": "close_open_orders_with_day",
		},
		{
			# BR-066 — whether a table may carry more than one bill at a time.
			"fieldname": "allow_multiple_orders_per_table",
			"fieldtype": "Check",
			"default": "0",
			"label": "Allow more than one bill on a table",
			"description": (
				"On: a table can carry several open bills at once — two couples sharing a "
				"large table, or a group that asked to be billed separately from the start. "
				"Off: a table has one bill, and a second attempt is refused. Off by default: "
				"a till that quietly opens a second bill on table four turns one party into "
				"two, and the mistake surfaces when somebody pays half of it."
			),
			"insert_after": "carried_orders_warning_at",
		},
		{
			"fieldname": "is_active",
			"fieldtype": "Check",
			"label": "Is Active",
			"default": "1",
			"insert_after": "allow_multiple_orders_per_table",
		},
		# `D-337` — **everything about stock that is the branch's, in one place.**
		# It was spread over four forms, and the warehouse asked for here was
		# read by nothing: stock left from the terminal's. Each field says what
		# it does; the last line reads out the one setting that is the site's.
		{
			"fieldname": "rpos_stock_section",
			"fieldtype": "Section Break",
			"label": "Stock",
			"insert_after": "is_active",
		},
		{
			"fieldname": "default_warehouse",
			"fieldtype": "Link",
			"options": "Warehouse",
			"label": "Branch Warehouse",
			"description": "Everything this branch sells is taken from this warehouse. Its terminals use it automatically; a terminal keeps a different one only if you set it on the terminal yourself.",
			"reqd": 1,
			"insert_after": "rpos_stock_section",
		},
		{
			"fieldname": "rpos_stock_cb",
			"fieldtype": "Column Break",
			"insert_after": "default_warehouse",
		},
		{
			"fieldname": "rpos_enforce_stock",
			"fieldtype": "Check",
			"label": "Refuse a Sale When Stock Is Short",
			"description": "Ticked: the till refuses an item sold as it comes — a bottle, a can, an add-on such as extra cheese — when none is left, and shows it as sold out. Unticked: the till never refuses; the item only says it has run out. Either way a dish with a recipe is never refused for its ingredients: mark the dish sold out at the till instead. It cannot be unticked while negative stock is not allowed.",
			"insert_after": "rpos_stock_cb",
		},
		{
			"fieldname": "rpos_stock_note",
			"fieldtype": "HTML",
			"insert_after": "rpos_enforce_stock",
		},
		{
			"fieldname": "rpos_address_section",
			"fieldtype": "Section Break",
			"label": "Address",
			"insert_after": "rpos_stock_note",
		},
		{
			"fieldname": "branch_address",
			"fieldtype": "Text",
			"label": "Branch Address",
			"insert_after": "rpos_address_section",
		},
		# D-191 — two numbers, and the reserved colour on the floor is worked out
		# from them each time it is drawn rather than stored on the table.
		{
			"fieldname": "rpos_reservations_section",
			"fieldtype": "Section Break",
			"label": "Reservations",
			"insert_after": "branch_address",
		},
		{
			"fieldname": "reservation_turn_minutes",
			"fieldtype": "Int",
			"default": "90",
			"label": "Expected Table Time (minutes)",
			"description": (
				"How long a party usually stays. A booked table is held this long before the "
				"booking, a walk-in seated inside that window is warned, and a second booking on "
				"the same table closer than this is refused. Toast and SevenRooms plan on the "
				"same figure — about an hour and a half for a couple."
			),
			"insert_after": "rpos_reservations_section",
		},
		{
			"fieldname": "reservation_grace_minutes",
			"fieldtype": "Int",
			"default": "15",
			"label": "Grace for Late Guests (minutes)",
			"description": (
				"How long a booked table waits after the booking time before it goes back to the "
				"floor. Fifteen minutes is the common practice. The booking stays expected until "
				"the day is closed, which records it as a no-show."
			),
			"insert_after": "reservation_turn_minutes",
		},
		{
			"fieldname": "rpos_appearance_section",
			"fieldtype": "Section Break",
			"label": "Appearance",
			"insert_after": "reservation_grace_minutes",
		},
		{
			"fieldname": "rpos_theme",
			"fieldtype": "Link",
			"options": "RPOS Theme",
			"label": "Theme",
			"description": (
				"The brand colours every terminal in this branch renders with, unless the terminal "
				"names its own. Empty falls through to the default theme (FR-15.2)."
			),
			"insert_after": "rpos_appearance_section",
		},
	],
	"Item": [
		{
			"fieldname": "rpos_section",
			"fieldtype": "Section Break",
			"label": "Restaurant POS",
			"collapsible": 1,
			"insert_after": "item_group",
		},
		{
			"fieldname": "pos_display_name_ar",
			"fieldtype": "Data",
			"label": "POS Display Name (Arabic)",
			"translatable": 1,
			"insert_after": "rpos_section",
		},
		# `D-324` — this item's own line for "N left" on its tile; empty follows
		# the restaurant's, in Restaurant POS Settings.
		{
			"fieldname": "rpos_low_stock_at",
			"fieldtype": "Int",
			"label": "Show What Is Left From",
			"non_negative": 1,
			"depends_on": "eval:doc.is_stock_item",
			"description": "For an item sold as it comes: its tile shows how many are left once that many or fewer remain. Empty uses the number in Restaurant POS Settings.",
			"insert_after": "pos_display_name_ar",
		},
		{
			"fieldname": "rpos_section_cb",
			"fieldtype": "Column Break",
			"insert_after": "rpos_low_stock_at",
		},
		{
			"fieldname": "default_production_center",
			"fieldtype": "Link",
			"options": "Production Center",
			"label": "Default Production Center",
			"description": "Kitchen routing priority level 5.",
			"insert_after": "rpos_section_cb",
		},
		{
			"fieldname": "rpos_modifier_section",
			"fieldtype": "Section Break",
			"label": "POS Modifier Groups",
			"collapsible": 1,
			"insert_after": "default_production_center",
		},
		{
			"fieldname": "pos_modifier_groups",
			"fieldtype": "Table",
			"options": "Modifier Group Assignment",
			"label": "Modifier Groups",
			"description": "Row order determines display order in the modifier popup.",
			"insert_after": "rpos_modifier_section",
		},
		# `D-285` — a combo is an item on the menu with its choices under it: the
		# till opens them like modifiers, and the items chosen are what is sold.
		#
		# `D-293` — the tick sits with the item's other POS settings, and the
		# section it opens is a full-width one like the modifiers', closed by a
		# break of its own: without it ERPNext's next fields (a column break among
		# them) fell into the section and squeezed the table into half the form.
		{
			"fieldname": "rpos_is_combo",
			"fieldtype": "Check",
			"label": "Combo",
			"description": "The guest buys the items below as one, and they are what leaves stock and what is sold.",
			"insert_after": "default_production_center",
		},
		# `D-378` — a dish whose price is said at the counter (the fish of the
		# day, a cake by the size it is cut): the till asks for it on every sale.
		{
			"fieldname": "rpos_open_price",
			"fieldtype": "Check",
			"label": "Open Price",
			"description": "The cashier types the price each time it is sold. It needs no price list row.",
			"insert_after": "rpos_is_combo",
		},
		{
			"fieldname": "rpos_combo_section",
			"fieldtype": "Section Break",
			"label": "Combo",
			"collapsible": 0,
			"depends_on": "rpos_is_combo",
			"insert_after": "pos_modifier_groups",
		},
		{
			"fieldname": "rpos_combo_pricing",
			"fieldtype": "Select",
			"label": "Combo Price",
			"options": "fixed\nsum",
			"default": "fixed",
			"description": "fixed: this item's own price, shared across the items. sum: the items' prices added up.",
			"insert_after": "rpos_combo_section",
		},
		{
			"fieldname": "rpos_combo_items",
			"fieldtype": "Table",
			"options": "POS Combo Item",
			"label": "Combo Items",
			"insert_after": "rpos_combo_pricing",
		},
		{
			"fieldname": "rpos_combo_end",
			"fieldtype": "Section Break",
			"insert_after": "rpos_combo_items",
		},
	],
	# The manager PIN belongs to a person, not a role (DECISIONS.md D-016).
	# Its value never reaches this column: restaurant_pos.utils.manager_pin
	# strips it on validate and stores a one-way hash instead (D-015).
	"User": [
		{
			"fieldname": "rpos_section",
			"fieldtype": "Section Break",
			"label": "Restaurant POS",
			"collapsible": 1,
			"insert_after": "role_profile_name",
		},
		{
			"fieldname": "pos_manager_pin",
			"fieldtype": "Password",
			"label": "POS PIN",
			"description": "5 digits. Signs this person in at the till and approves overrides. Write-only — never displayed.",
			"no_copy": 1,
			"insert_after": "rpos_section",
		},
		{
			# D-094 — a keyed digest of the PIN, so signing in is one indexed
			# read instead of a slow hash per member of staff. Hidden and
			# read-only because it is PIN-equivalent for lookup: it must never
			# be shown, exported or returned by an API.
			"fieldname": "rpos_pin_lookup",
			"fieldtype": "Data",
			"label": "PIN Lookup",
			"hidden": 1,
			"read_only": 1,
			"no_copy": 1,
			"print_hide": 1,
			"search_index": 1,
			"insert_after": "pos_manager_pin",
		},
	],
	# A delivery platform or a corporate account is settled on a statement, not
	# at the till: the customer owes the restaurant and pays monthly. ERPNext
	# has no "credit" mode of payment type, so the distinction is a flag
	# (DECISIONS.md D-029).
	# A return is an invoice in reverse, and a cashier reads a bill by its short
	# daily number — not by `ACC-SINV-2026-00042` (`D-143`). The credit note
	# takes the next number in the branch's own sequence, so a day reads 20 for
	# the sale and 21 for the return of part of it. `Restaurant Order` carries
	# the same number for a sale; this is where a document that is *not* an
	# order carries one.
	SALE: [
		{
			"fieldname": "rpos_daily_number",
			"fieldtype": "Int",
			"label": "RPOS Daily Number",
			"read_only": 1,
			"no_copy": 1,
			"description": "The short number the till shows for this document, in the branch's daily sequence.",
			"insert_after": "is_return",
		},
		# `D-313` — which branch sold it, and which batch took it to the books.
		# Together they are how a posting finds a day's unposted sales without
		# reading every invoice the company has (`after_migrate` indexes the pair).
		{
			"fieldname": "rpos_branch",
			"fieldtype": "Link",
			"options": "Branch",
			"label": "RPOS Branch",
			"read_only": 1,
			"insert_after": "rpos_daily_number",
		},
		{
			"fieldname": "rpos_posting_batch",
			"fieldtype": "Link",
			"options": "POS Posting Batch",
			"label": "RPOS Posting Batch",
			"read_only": 1,
			# A credit note is copied from its sale, and must not arrive already
			# claimed by the batch that posted the sale.
			"no_copy": 1,
			"description": "The batch that posted this sale to the accounts and the stock ledger. Empty means it is not posted yet.",
			"insert_after": "rpos_branch",
		},
	],
	# `D-313` — what a posting made names the batch it was made for, so an
	# accountant can go from an entry in the books to the day at the till.
	POSTED_ENTRY: [_made_by_a_batch("is_consolidated")],
	"Stock Entry": [_made_by_a_batch("stock_entry_type")],
	"Journal Entry": [_made_by_a_batch("voucher_type")],
	# `D-284` — an add-on sold as its own line, bound to the dish it was chosen
	# on. Copied onto a credit note by `make_return_doc`, which is how a return
	# of the dish finds its add-ons and a recipe keeps its removals.
	SALE_ITEM: [
		# `D-314` — what a unit of this line cost, stamped by the posting that took
		# it from the warehouse. A POS Invoice has no stock ledger of its own to
		# read a cost from, and a cost is a fact about the day it was posted: it is
		# written once, here, where every report already looks.
		{
			"fieldname": LINE_COST,
			"fieldtype": "Float",
			"precision": "6",
			"label": "RPOS Cost Rate",
			"read_only": 1,
			"no_copy": 1,
			"description": "What one stock unit of this line cost when its day was posted. Empty until then.",
			"insert_after": "stock_qty",
		},
		# `D-315` — on a credit note: this line came back and was thrown away. A
		# returned bottle of water goes back on the shelf; a returned burger does
		# not, and its cost is waste rather than cost of sales.
		{
			"fieldname": WASTED,
			"fieldtype": "Check",
			"label": "RPOS Wasted",
			"read_only": 1,
			"no_copy": 1,
			"description": "On a return: this line was thrown away, so its stock does not go back to the warehouse.",
			"insert_after": LINE_COST,
		},
		{
			"fieldname": "rpos_order_item",
			"fieldtype": "Data",
			"label": "RPOS Order Line",
			"read_only": 1,
			"hidden": 1,
			"insert_after": "item_name",
		},
		{
			"fieldname": "rpos_is_addon",
			"fieldtype": "Check",
			"label": "Add-on",
			"read_only": 1,
			"description": "Chosen on the dish above it at the till.",
			"insert_after": "rpos_order_item",
		},
		{
			"fieldname": "rpos_combo",
			"fieldtype": "Link",
			"options": "Item",
			"label": "Combo",
			"read_only": 1,
			"description": "The combo this item was sold in.",
			"insert_after": "rpos_is_addon",
		},
		{
			"fieldname": "rpos_removed",
			"fieldtype": "Small Text",
			"label": "Left Out of the Recipe",
			"read_only": 1,
			"hidden": 1,
			"insert_after": "rpos_combo",
		},
	],
	# **The two rules ERPNext's program has no field for** (`D-189`). Earning,
	# the value of a point and the expiry are ERPNext's own fields; these are
	# the limits on *spending*, which ERPNext leaves to whoever builds the till.
	"Loyalty Program": [
		{
			"fieldname": "rpos_section",
			"fieldtype": "Section Break",
			"label": "Restaurant POS",
			"insert_after": "expiry_duration",
		},
		{
			"fieldname": "rpos_min_redeem_points",
			"fieldtype": "Int",
			"label": "Minimum Balance to Spend",
			"default": "100",
			"description": "A customer spends nothing until they hold at least this many points.",
			"insert_after": "rpos_section",
		},
		{
			"fieldname": "rpos_max_redeem_percent",
			"fieldtype": "Percent",
			"label": "Most of a Bill Points May Pay",
			"default": "50",
			"description": "Taken of what is left after the offers and any discount.",
			"insert_after": "rpos_min_redeem_points",
		},
	],
	"Mode of Payment": [
		{
			"fieldname": "rpos_is_credit",
			"fieldtype": "Check",
			"label": "Settled on Account (Credit)",
			"description": (
				"Nothing is counted in the drawer for it. What is paid with it is posted to "
				"the account below — a delivery platform's, say — and settled there later."
			),
			"insert_after": "type",
		},
		{
			# `D-264` — what makes a method spend a gift card. It was the method's
			# name, so a card method called anything else — another language, a
			# typo — took money like cash and asked for no card.
			"fieldname": "rpos_is_gift_card",
			"fieldtype": "Check",
			"label": "Gift Card",
			"description": (
				"The cashier is asked for the card's number and its balance pays. "
				"One method only; its account is the gift card liability."
			),
			"insert_after": "rpos_is_credit",
		},
	],
	"Item Group": [
		{
			"fieldname": "rpos_section",
			"fieldtype": "Section Break",
			"label": "Restaurant POS",
			"collapsible": 1,
			"insert_after": "is_group",
		},
		{
			"fieldname": "default_production_center",
			"fieldtype": "Link",
			"options": "Production Center",
			"label": "Default Production Center",
			"description": "Kitchen routing priority level 6.",
			"insert_after": "rpos_section",
		},
	],
	"POS Profile": [
		{
			"fieldname": "rpos_section",
			"fieldtype": "Section Break",
			"label": "Restaurant POS",
			"insert_after": "company",
		},
		# **The terminal's own branch** (`D-391`). It reached its branch through its
		# hall, and ten places in the code worked that out; this is where the
		# answer will be read from. Filled from the hall by a patch and kept equal
		# to it on every save until the reading moves here (stage 3).
		{
			"fieldname": "rpos_branch",
			"fieldtype": "Link",
			"options": "Branch",
			"label": "Branch",
			"description": "The branch this device sells in. Its day, drawer, stock and invoice numbers follow it.",
			# Carried by Duplicate (`D-395`): a copy of a till is a till of the same
			# branch, hall or no hall. Was `no_copy` while every till had a hall to
			# take it from again (`D-393`); a counter till has none, and its copy
			# came out belonging to no branch. Written as 0, not left out: the
			# update of an existing field only sets the keys it is given.
			"no_copy": 0,
			"insert_after": "rpos_section",
		},
		{
			"fieldname": "restaurant_section",
			"fieldtype": "Link",
			"options": "Restaurant Section",
			"label": "Default Hall",
			# `D-395` — the device belongs to its branch (above); the hall only
			# decides which one the floor opens on. A counter or a supermarket
			# till leaves it empty.
			"description": "Optional. The hall the floor opens on. The device can still sell at any hall of its branch, and takeaway.",
			"insert_after": "rpos_branch",
		},
		# **The terminal's own part of its invoice numbers** (`D-309`), unique
		# within the branch. Each terminal counts on its own series, so tills do
		# not queue behind one counter.
		{
			"fieldname": "rpos_device_number",
			"fieldtype": "Data",
			"label": "Device Number",
			"no_copy": 1,
			"description": "This terminal's part of its invoice numbers: branch, device, count — e.g. 1002-01-000001. Leave empty and the next free number in the branch is taken. It cannot change once the terminal has invoices.",
			"insert_after": "restaurant_section",
		},
		{
			"fieldname": "screen_layout",
			"fieldtype": "Link",
			"options": "POS Screen Layout",
			"label": "Screen Layout",
			"insert_after": "rpos_device_number",
		},
		{
			"fieldname": "rpos_section_cb",
			"fieldtype": "Column Break",
			"insert_after": "screen_layout",
		},
		{
			"fieldname": "default_printer",
			"fieldtype": "Link",
			"options": "POS Printer",
			"label": "Default Printer",
			"description": "The printer this terminal prints the customer's receipt on.",
			"insert_after": "rpos_section_cb",
		},
		{
			"fieldname": "receipt_template",
			"fieldtype": "Link",
			"options": "POS Print Template",
			"label": "Receipt Template",
			"description": "The customer receipt this terminal prints, as chosen — Preview it on the template. Empty uses the branch's template, then the default (D-214).",
			"link_filters": '[["POS Print Template","template_type","=","customer_receipt"]]',
			"insert_after": "default_printer",
		},
		{
			"fieldname": "restaurant_shift",
			"fieldtype": "Link",
			"options": "Restaurant Shift",
			"label": "Current Restaurant Shift",
			"no_copy": 1,
			"insert_after": "receipt_template",
		},
		{
			"fieldname": "rpos_theme",
			"fieldtype": "Link",
			"options": "RPOS Theme",
			"label": "Theme",
			"description": "This terminal's brand colours. Empty falls through to the branch's theme, then the default (FR-15.2).",
			"insert_after": "restaurant_shift",
		},
		{
			"fieldname": "rpos_order_types_section",
			"fieldtype": "Section Break",
			"label": "Allowed Order Types",
			"insert_after": "rpos_theme",
		},
		{
			"fieldname": "allowed_order_types",
			"fieldtype": "Table",
			"options": "POS Profile Order Type",
			"label": "Allowed Order Types",
			"description": "Leave empty to show every active order type on this terminal.",
			"insert_after": "rpos_order_types_section",
		},
		# **Which machine this terminal is** (`D-226`). One POS Profile is one
		# till: the device pairs once with a short code and keeps a token, and
		# no second machine can sell on it until a manager unpairs this one.
		{
			"fieldname": "rpos_device_section",
			"fieldtype": "Section Break",
			"label": "Paired Device",
			"insert_after": "allowed_order_types",
		},
		{
			"fieldname": "rpos_device_name",
			"fieldtype": "Data",
			"label": "Device",
			"read_only": 1,
			"no_copy": 1,
			"description": "The machine this terminal is paired with. Empty means it is free to pair.",
			"insert_after": "rpos_device_section",
		},
		{
			"fieldname": "rpos_paired_at",
			"fieldtype": "Datetime",
			"label": "Paired At",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "rpos_device_name",
		},
		{
			"fieldname": "rpos_device_cb",
			"fieldtype": "Column Break",
			"insert_after": "rpos_paired_at",
		},
		{
			"fieldname": "rpos_paired_by",
			"fieldtype": "Link",
			"options": "User",
			"label": "Paired By",
			"read_only": 1,
			"no_copy": 1,
			"insert_after": "rpos_device_cb",
		},
		{
			"fieldname": "rpos_pairing_expires",
			"fieldtype": "Datetime",
			"label": "Pairing Code Expires",
			"read_only": 1,
			"no_copy": 1,
			"description": "While a pairing code is outstanding. Empty once it is used or replaced.",
			"insert_after": "rpos_paired_by",
		},
		# Digests, never the values: a stolen database hands over neither a live
		# code nor a working device token (`manager_pin.lookup_of`).
		{
			"fieldname": "rpos_device_token_hash",
			"fieldtype": "Data",
			"label": "Device Token Hash",
			"read_only": 1,
			"hidden": 1,
			"no_copy": 1,
			"insert_after": "rpos_pairing_expires",
		},
		{
			"fieldname": "rpos_pairing_code_hash",
			"fieldtype": "Data",
			"label": "Pairing Code Hash",
			"read_only": 1,
			"hidden": 1,
			"no_copy": 1,
			"insert_after": "rpos_device_token_hash",
		},
		# D-301 — the bell's sound, per terminal: a counter by the street and a
		# pass by the grill are not the same room.
		{
			"fieldname": "rpos_alert_section",
			"fieldtype": "Section Break",
			"label": "Alert Sound",
			"collapsible": 1,
			"insert_after": "rpos_pairing_code_hash",
		},
		{
			"fieldname": "rpos_alert_sound",
			"fieldtype": "Check",
			"label": "Play a sound for a new alert",
			"default": "1",
			"insert_after": "rpos_alert_section",
		},
		{
			"fieldname": "rpos_alert_tone",
			"fieldtype": "Select",
			"label": "Tone",
			# Keys of `public/alert_tones.json` — a test holds the two together.
			"options": "chime\nbell\nbeep\nalarm",
			"default": "chime",
			"depends_on": "rpos_alert_sound",
			"insert_after": "rpos_alert_sound",
		},
		{
			"fieldname": "rpos_alert_cb",
			"fieldtype": "Column Break",
			"insert_after": "rpos_alert_tone",
		},
		{
			"fieldname": "rpos_alert_volume",
			"fieldtype": "Int",
			"label": "Volume",
			"default": "70",
			"description": "From 1 to 100. The device's own volume still applies on top.",
			"depends_on": "rpos_alert_sound",
			"insert_after": "rpos_alert_cb",
		},
		# Closes ours, so the profile's own fields that follow (customer,
		# warehouse…) are not drawn inside "Alert Sound". They were inside
		# "Paired Device" before it — the user saw them mixed in (`D-301`).
		{
			"fieldname": "rpos_alert_end",
			"fieldtype": "Section Break",
			"insert_after": "rpos_alert_volume",
		},
	],
}

# No per-profile template fields, despite what `FR-7.2` anticipated (D-085).
#
# `printing.resolve_template` already picks a branch's template over the shipped
# default, and that is the difference restaurants actually have. Four Link
# fields nothing sets and nobody has asked for would be four more places to look
# when a receipt prints wrong. `resolve_template` takes an `explicit` argument,
# so the day a terminal genuinely needs its own template, the field is one line
# and the resolution order is already written.


#: Roles that settle an order and therefore create a Sales Invoice.
INVOICING_ROLES = (
	"POS Cashier",
	"POS Senior Cashier",
	"POS Manager",
	"Restaurant Manager",
	"Restaurant Admin",
)


#: What a POS role needs on ERPNext's own DocTypes, and nothing more.
#:
#: `08_Security.md` §2 already specifies "Read: Item, Customer" for a cashier;
#: it was never granted, so the first non-Administrator to take a payment hit
#: ERPNext's own permission checks. Those checks call
#: ``frappe.has_permission()`` directly and ignore the document-level
#: ``ignore_permissions`` our code passes, so a role permission is the only
#: thing that satisfies them.
#:
#: ``Account`` gets ``select`` rather than ``read``: enough to be attached to an
#: invoice, not enough to open the chart of accounts or read a balance.
#: ERPNext's own answer here is the broad ``Accounts User`` role, which would
#: hand a cashier the whole accounting module.
ERPNEXT_PERMISSIONS = {
	"Item": {"read": 1},
	"Customer": {"read": 1},
	"Account": {"select": 1},
}


def grant_erpnext_permissions() -> None:
	"""Give the POS roles the ERPNext rights their work requires.

	Idempotent: a DocType a role already has a Custom DocPerm for is left alone,
	so an administrator who tightened or widened something keeps their change.
	"""
	from frappe.permissions import add_permission, update_permission_property

	for doctype, rights in ERPNEXT_PERMISSIONS.items():
		if not frappe.db.exists("DocType", doctype):
			continue

		for role in INVOICING_ROLES:
			if not frappe.db.exists("Role", role):
				continue

			if frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role}):
				continue

			add_permission(doctype, role, 0)
			for ptype, value in rights.items():
				update_permission_property(doctype, role, 0, ptype, value)

			# add_permission() grants read by default; drop it where the map
			# asks for something narrower.
			if "read" not in rights:
				update_permission_property(doctype, role, 0, "read", 0)


#: ERPNext's own fields that a till cannot work without, made required on the
#: form rather than refused at the payment screen (`D-231`).
#:
#: A `POS Profile` with no default customer looks complete, saves without a
#: word, and then refuses every sale: ERPNext needs a customer on the invoice,
#: so `invoice_blocker` reports it and the payment screen shows it in red. The
#: user met exactly that. The form is where the manager is standing when the
#: field is empty, so the form is where it is asked for.
REQUIRED_ERPNEXT_FIELDS = {
	("POS Profile", "customer"): (
		"Every sale on this terminal is invoiced to this customer unless the cashier "
		"names another. Payment is refused while it is empty."
	),
}


def require_erpnext_fields() -> None:
	"""Mark those fields required, and say why on the field itself.

	A Property Setter, not an edit to ERPNext's own DocType (`CLAUDE.md` §3):
	an upgrade replaces the DocType and leaves this standing.
	"""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	for (doctype, fieldname), description in REQUIRED_ERPNEXT_FIELDS.items():
		if not frappe.db.exists("DocType", doctype):
			continue

		make_property_setter(doctype, fieldname, "reqd", 1, "Check", validate_fields_for_doctype=False)
		make_property_setter(
			doctype, fieldname, "description", description, "Text", validate_fields_for_doctype=False
		)


GUIDE_ROUTE = "/rpos-guide"


def add_guide_to_help_menu() -> None:
	"""«مساعدة ← دليل نقاط البيع» on every office page (`D-262`).

	Frappe's own `standard_help_items` hook is read only while the help menu is
	still empty — on a new site's first install — so an existing site never
	sees it. The row is added here instead, once: matched on its route, so a
	label the manager renamed is theirs and nothing is doubled on migrate.
	"""
	navbar = frappe.get_single("Navbar Settings")
	if any(row.route == GUIDE_ROUTE for row in navbar.help_dropdown):
		return

	navbar.append(
		"help_dropdown",
		{"item_label": "POS User Guide", "item_type": "Route", "route": GUIDE_ROUTE, "is_standard": 0},
	)
	navbar.save(ignore_permissions=True)


def ensure_portion_uom():
	"""The unit an add-on is sold in when a choice is not one stock unit (`D-284`)."""
	from restaurant_pos.utils.addons import PORTION

	if not frappe.db.exists("UOM", PORTION):
		frappe.get_doc({"doctype": "UOM", "uom_name": PORTION, "must_be_whole_number": 0}).insert(
			ignore_permissions=True
		)


def after_install():
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
	ensure_portion_uom()
	require_erpnext_fields()
	grant_erpnext_permissions()
	create_default_templates()
	add_guide_to_help_menu()
	desk_tiles.setup()
	frappe.db.commit()

	# Shipped defaults run on install only. See setup/defaults.py for why they
	# must never be re-applied on migrate.
	create_default_data()

	# `D-246` — the reasons exist now, so give them somewhere in the books to
	# land. Never overwrites an account or a mapping somebody already chose.
	cash_accounts.setup()

	# `D-319` — and the delivery platforms' payment methods, made just above,
	# somewhere to keep what each platform owes.
	platform_accounts.setup()


def after_migrate():
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
	ensure_portion_uom()
	require_erpnext_fields()
	grant_erpnext_permissions()

	# Unlike the defaults above, templates are re-checked on every migrate: they
	# are keyed by title and an existing one is never touched, and a site that
	# had the app before Phase 3 has no templates at all — which is a site that
	# cannot print.
	create_default_templates()

	# `D-350` — a site with no permission set at all is one whose install never
	# reached the defaults, not one that chose to have none: every till role then
	# signs nobody in, and the pad says only "not recognised". Nothing a
	# restaurant configured is touched — each default is made only if missing.
	if not frappe.db.count("POS Permission Set"):
		create_default_data()

	# `D-256` — and on migrate rather than install alone, for the same reason:
	# every site that had this app before gift cards existed needs the liability
	# account and the payment mode, or the feature is simply absent there. It
	# creates nothing that is already present and overwrites nothing at all.
	gift_card_accounts.setup()

	# `D-315` — the account a thrown-away return is charged to. Created once and
	# never overwritten, like the gift cards' and the drawer's.
	waste_account.setup()

	# `D-357` — where the accountant writes off a drawer's difference. Same rule:
	# made once, never overwritten.
	over_short_account.setup()

	# `D-347` — the block the office pages draw their tiles with.
	desk_tiles.setup()

	# `D-319` — what a delivery platform owes sits on an account its payment
	# method names. A site from before this has the methods and no accounts.
	platform_accounts.setup()

	# Every site that had the app before the guide was served needs the menu row.
	add_guide_to_help_menu()

	# `D-309` — here rather than in a patch, because the two number fields are
	# custom fields and exist only once the line at the top has run. A site from
	# before invoice numbers were branch-terminal-count gets both numbers and a
	# counter per terminal now, not inside a customer's first payment. It numbers
	# only what has none.
	from restaurant_pos.utils import invoice_number

	invoice_number.number_existing()

	# `D-313` — a posting asks "this branch's sales no batch has taken", on every
	# day close, over a table that only grows. Without the pair indexed that
	# question read a million invoices to find forty (38 s, measured).
	frappe.db.add_index(SALE, ["rpos_branch", "rpos_posting_batch"], "rpos_unposted")
	# `D-321` — what is on bills still open, for the same count.
	frappe.db.add_index("Restaurant Order", ["branch", "status"], "rpos_open_bills")

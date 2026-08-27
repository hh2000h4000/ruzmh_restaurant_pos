/**
 * English is the **source of truth for the key set**, not the default language.
 *
 * `MessageKey` and `PluralKey` are derived from this file, so every other
 * locale is typed against it and a missing translation fails the build instead
 * of showing a raw key to a cashier.
 *
 * Keys are flat and dotted so they grep cleanly: `home.` finds everything the
 * home screen says.
 */

export const messages = {
  // Actions and chrome
  "action.cancel": "Cancel",
  "action.back": "Back",
  "action.undo": "Undo",
  "action.refresh": "Refresh",
  "action.remove": "Remove",
  "action.authorize": "Authorize",
  "common.loading": "Loading…",
  "common.soon": "Not built yet",
  "common.listSeparator": ", ",
  "currency.sar": "SAR",
  /** The language this button switches **to**, written in that language. */
  "lang.other": "العربية",

  // Connection banner
  "conn.offline": "Offline — actions are saved on this device",
  "conn.signedOut": "Not signed in",
  "conn.signIn": "Sign in",
  "conn.syncing": "Syncing…",
  "conn.syncNow": "Sync now",
  "conn.staleConfig": "Working from this device's copy, saved {when}.",

  // Errors raised by the API client
  "err.noCsrf": "The page loaded without a security token — sign out and reload.",
  "err.offline": "No connection to the server",
  "err.failed": "The request could not be completed ({status})",

  // Device setup
  "setup.signInFirst": "Sign in first, then try again.",
  "setup.title": "Device setup",
  "setup.hint": "Choose the terminal this device is. Asked once.",
  "setup.empty": "No terminal is available for your user. Ask the manager to add you to a POS profile.",

  // Home
  "home.newOrder": "Open a new order",
  "home.noOrderTypes": "No order type is available on this device.",
  "home.shiftOpen": "Shift open",
  "home.shiftClosed": "No open shift",
  "home.shiftRequired": "Open a shift before taking orders.",
  "home.shiftFromDesk": "A shift is opened from the Restaurant Shift screen for now.",
  "home.openOrders": "Open orders",
  "home.openOrdersEmpty": "Nothing on the floor. Pick an order type to start one.",
  "home.openOrdersFailed": "The open orders could not be loaded.",
  "home.scopeMine": "Mine",
  "home.scopeAll": "All",
  "home.cashierOnDuty": "On duty",
  "home.floorPlan": "Floor plan",
  "home.closedInvoices": "Closed invoices",
  "home.reservations": "Reservations",
  "home.shiftReport": "Shift report",

  // Order cards and statuses
  "card.table": "Table {number}",
  "status.draft": "Draft",
  "status.active": "Active",
  "status.in_kitchen": "In kitchen",
  "status.pending_payment": "Awaiting payment",

  // Tables
  "tables.title": "Tables",
  "tables.table": "Table",
  "tables.noSection": "This device is not linked to a section.",
  "tables.empty": "No tables in this section.",
  "tables.covers": "Number of guests",
  "tables.start": "Open the order",
  "table.available": "Free",
  "table.occupied": "Occupied",
  "table.reserved": "Reserved",
  "table.cleaning": "Cleaning",
  "table.inactive": "Out of service",

  // Order screen
  "order.typeUnavailable": "That order type is not available on this device.",
  "order.pickTableFirst": "Choose a table first.",
  "order.customerPending": "This type needs a customer — the customer screen is still being built.",
  "order.notRouted": "Not routed to a kitchen: {items} — printing on the cashier printer.",
  "order.sendToKitchen": "Send to kitchen",
  "order.pay": "Pay",
  "order.cancelOrder": "Cancel order",
  "order.voidReason": "Reason for voiding",
  "order.voidPlaceholder": "For example: the customer changed their mind",
  "order.voidItem": "Void the item",
  "order.cancelBody": "The whole order will be cancelled, and the kitchen told about anything already sent.",
  "order.confirmCancel": "Confirm the cancellation",
  "order.pendingSync": "Saved on this device — waiting for the connection to reach the server.",

  // Order panel
  "panel.title": "Order items",
  "panel.inKitchen": "In kitchen",
  "panel.addSame": "Add another",
  "panel.empty": "No items added yet.",
  "totals.subtotal": "Subtotal",
  "totals.discount": "Discount",
  "totals.tax": "VAT",
  "totals.total": "Total",

  // Item picker
  "picker.search": "Search for an item",
  "picker.noPrice": "No price",
  "picker.noResults": "No results.",
  "picker.empty": "No items available.",

  // Modifiers
  "mod.single": "choose one",
  "mod.multi": "multiple choice",
  "mod.note": "Special note",
  "mod.priceDelta": "Added to the price:",
  "mod.add": "Add to the order",
  "mod.choose": "Choose:",

  // Payment
  "pay.title": "Payment",
  "pay.paid": "Paid",
  "pay.alreadyPaid": "This order is paid — invoice {invoice}",
  "pay.newOrder": "New order",
  "pay.methods": "Payment methods",
  "pay.forcedMethod": "This type is paid by {method} only.",
  "pay.received": "Amount received (for change)",
  "pay.discounts": "Discounts",
  "pay.manualDiscount": "Manual discount",
  "pay.discountType": "Discount type",
  "pay.exceedsLimit": "Above your limit ({limit}) — a manager must authorize it.",
  "pay.authorized": "Authorized",
  "pay.loyaltySoon": "Loyalty is not available yet.",
  "pay.summary": "Order summary",
  "pay.remaining": "Remaining",
  "pay.change": "Change due",
  "pay.confirm": "Confirm payment and issue the invoice",
  "pay.needsManager": "Manager authorization required",
  "pay.discountExceeds": "A {value} discount is above your limit.",
  "pay.managerPin": "Manager PIN",
  "pay.reasonRequired": "Reason (required)",
} as const;

export const plurals = {
  "count.items": { one: "{n} item", other: "{n} items" },
  "count.covers": { one: "{n} guest", other: "{n} guests" },
  "count.seats": { one: "{n} seat", other: "{n} seats" },
  "count.minutes": { one: "{n} min", other: "{n} min" },
  "count.openOrders": { one: "{n} open order", other: "{n} open orders" },
  "count.queued": { one: "{n} action waiting", other: "{n} actions waiting" },
  "count.syncFailed": { one: "{n} action failed", other: "{n} actions failed" },
} as const;

export default { messages, plurals };

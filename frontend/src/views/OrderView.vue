<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import type { ModifierChoice, OpenOrder, OrderLine } from "@/api/order";
import AppIcon from "@/components/AppIcon.vue";
import BaseDialog from "@/components/BaseDialog.vue";
import CustomerDialog from "@/components/order/CustomerDialog.vue";
import ItemPicker from "@/components/order/ItemPicker.vue";
import LineDetailDialog from "@/components/order/LineDetailDialog.vue";
import ModifierDialog from "@/components/order/ModifierDialog.vue";
import OrderActionBar, { type OrderAction } from "@/components/order/OrderActionBar.vue";
import NoteEditor from "@/components/order/NoteEditor.vue";
import OrderPanel from "@/components/order/OrderPanel.vue";
import OrderTypeChangeDialog from "@/components/order/OrderTypeChangeDialog.vue";
import CloseDayDialog from "@/components/shift/CloseDayDialog.vue";
import CloseTillDialog from "@/components/shift/CloseTillDialog.vue";
import OpenTillDialog from "@/components/shift/OpenTillDialog.vue";
import ShiftMenu from "@/components/shift/ShiftMenu.vue";
import FloorPane from "@/components/order/FloorPane.vue";
import NewOrderPane from "@/components/order/NewOrderPane.vue";
import OrderBottomNav, { type NavEntry } from "@/components/order/OrderBottomNav.vue";
import OpenOrdersPanel from "@/components/pos/OpenOrdersPanel.vue";
import { useOpenOrders } from "@/composables/useOpenOrders";
import { formatNumber, t } from "@/i18n";
import { useOrderStore } from "@/stores/order";
import { useSessionStore } from "@/stores/session";
import { useShiftStore } from "@/stores/shift";
import type { FloorTable } from "@/api/table";
import type { CatalogItem, OrderType } from "@/types/session";

/**
 * The till. Every screen a cashier uses, and the only one there is (D-055).
 *
 * It was Screen 3 of six, reached from a home screen that listed order types on
 * the left and open orders on the right. Both of those are panes here, so that
 * screen was a second way to do what this one already does — and a cashier who
 * paid a bill was thrown back to it, out of the flow, to start the next one.
 * It is gone; `/` is this.
 *
 * **It runs with no order in hand.** That is the resting state: the orders pane,
 * the floor, the shift menu, and a bill panel that says there is nothing on it
 * yet. A closed shift does not lock the screen either — the cashier can still
 * read yesterday's orders; what a closed shift stops is money moving (BR-044),
 * and that stop happens at the tap, with the reason attached.
 *
 * Every action is a server call; nothing about the order is decided here
 * (`02_backend_rules.md`).
 */
const route = useRoute();
const router = useRouter();
const session = useSessionStore();
const orders = useOrderStore();
const shift = useShiftStore();

const startupError = ref<string | null>(null);
const pendingItem = ref<CatalogItem | null>(null);
const pendingQty = ref(1);
const voidTarget = ref<OrderLine | null>(null);
const voidReason = ref("");
const cancelling = ref(false);
const cancelReason = ref("");

const orderType = computed(
  () => session.orderTypes.find((type) => type.name === orders.order?.order_type) ?? null,
);

/**
 * Nothing on this bill may change.
 *
 * `session.canSell` is in here, not only on the item tiles: **taking a line
 * off is cart work too** (D-056). A bill that shrank after its shift was
 * counted is a shortfall nobody can trace, and reading an old order to check
 * what was on it must not come with the buttons that alter it.
 */
const locked = computed(() => orders.busy || orders.isClosed || !session.canSell);

/**
 * The menu itself stays live while the shift is shut, deliberately.
 *
 * The tap is what asks the question, and the answer carries the button that
 * fixes it. A greyed-out menu explains nothing — it is `locked` that takes the
 * cart's own controls away.
 */
const pickerDisabled = computed(() => orders.busy || orders.isClosed);

onMounted(() => {
  // The menu offers what the shift allows, so it has to know the shift.
  void shift.refresh();
  void startFromRoute();
});

/**
 * Do what the address asked for: nothing, that order, or a new one of that type.
 *
 * Run on every route change rather than only on mount, because the screen never
 * unmounts now — paying a bill, tapping another order and starting a new one all
 * land back here.
 */
async function startFromRoute(): Promise<void> {
  startupError.value = null;

  const existing = route.params.orderName as string | undefined;
  if (existing) {
    pane.value = "items";
    if (existing !== orders.order?.order_name) await orders.open(existing);
    return;
  }

  const typeName = route.params.orderType as string | undefined;
  if (!typeName) {
    // The resting state is the **menu**, not a list of orders (D-056). A till
    // that opens on a list looks like a filing cabinet; the cashier's job is in
    // front of them, and the list is one tap away in the bar.
    // `?pane=new` is how the payment screen says "straight into the next one".
    orders.clear();
    pane.value = route.query.pane === "new" ? "new" : "items";
    return;
  }

  const type = session.orderTypes.find((candidate) => candidate.name === typeName);
  if (!type) {
    startupError.value = t("order.typeUnavailable");
    return;
  }

  orders.clear();
  // Where the cashier lands if the type cannot open right now — a closed shift,
  // a table to pick, a customer to find. Never the menu pane with no bill under
  // it, which is a wall of buttons that do nothing.
  pane.value = "new";
  await startAnother(type);
}

// --------------------------------------------------------------------------
// The working column (D-039)
// --------------------------------------------------------------------------

/**
 * The bill stays; only this column changes.
 *
 * Leaving the screen to look at the floor is what made the old flow feel like
 * two applications. Here the order in hand is never put down.
 */
const pane = ref("items");
const floorLayout = ref<"list" | "grid">("list");
const {
  error: floorError,
  loading: floorLoading,
  maySeeEveryone: floorMaySeeEveryone,
  scope: floorScope,
  search: floorSearch,
  searching: floorSearching,
  sort: floorSort,
  view: floorView,
  visible: floorOrders,
} = useOpenOrders();

/**
 * The four places, along the bottom (D-042).
 *
 * "New" sits among them rather than above them. It is the one entry that
 * changes something — it leaves the order in hand open and starts another — but
 * a filled block among four signposts turns a bar into an advertisement.
 */
const navEntries = computed<NavEntry[]>(() => [
  // First, where the hand starts: a new order is the commonest thing asked of
  // this bar, and the reading edge is the cheapest place to reach.
  { key: "new", label: "nav.new", icon: "plus" },
  { key: "items", label: "order.paneItems", icon: "grid" },
  {
    key: "orders",
    label: "nav.orders",
    icon: "document",
    count: floorView.value === "open" ? floorOrders.value.length : 0,
  },
  { key: "tables", label: "nav.tables", icon: "floorPlan" },
  // D-048 — the till's occasional operations, and the way home. A menu rather
  // than four more places nobody visits during a rush.
  { key: "menu", label: "nav.menu", icon: "more" },
]);

function onNavigate(key: string): void {
  // Walking away from the question cancels it; a table still marked "waiting"
  // would seat the next type the cashier taps for an unrelated reason.
  if (key !== "new") pendingTable.value = null;

  if (key === "menu") {
    menuOpen.value = !menuOpen.value;
    return;
  }

  menuOpen.value = false;
  pane.value = key;
}

// --------------------------------------------------------------------------
// The till menu (D-048)
// --------------------------------------------------------------------------

const menuOpen = ref(false);
const openingTill = ref(false);
const closingTill = ref(false);
const closingDay = ref(false);

function onMenu(key: string): void {
  menuOpen.value = false;

  if (key === "openTill") openingTill.value = true;
  else if (key === "closeTill") closingTill.value = true;
  else if (key === "closeDay") closingDay.value = true;
  else if (key === "logout") signingOut.value = true;
}

/** Confirmed, because signing out by accident mid-rush is a real annoyance. */
const signingOut = ref(false);

function signOut(): void {
  // Frappe owns the session (04 §7); this app only sends the cashier to its
  // logout and lets the redirect land wherever the site says.
  window.location.href = "/api/method/logout";
}

/**
 * Start another order and leave this one open (D-042).
 *
 * Nothing is "held": the order in hand is already a `Restaurant Order` on the
 * server, and the cashier finds it again under **الطلبات**. A customer who
 * takes their time paying stops blocking the queue, and no new concept was
 * needed to allow it.
 */
async function startAnother(orderType: OrderType): Promise<void> {
  // BR-044 — before any of the questions below, because none of them matter
  // if the order cannot be created at the end of them.
  if (!maySell()) return;

  // The cashier came here from a table they had already tapped: this answers
  // the question the floor could not.
  const waiting = pendingTable.value;
  if (waiting) {
    await openAt(waiting, orderType);
    return;
  }

  // **Only** when the type says so. A restaurant with no table plan opens
  // dine-in and the customer takes a seat; `requires_table` is what decides,
  // per type, and it always has been (05 §Restaurant Order Type).
  if (orderType.requires_table) {
    // A type that seats people picks the table first, so the order is never
    // created and then refused (FR-2.1 step 3).
    pane.value = "tables";
    seatingType.value = orderType;
    return;
  }

  // FR-2.1 step 4 — asked before the order exists, for the same reason a table
  // is: an order created and then refused for a missing customer is an order
  // the cashier has to cancel and ring again.
  if (orderType.customer_mode === "required") {
    customerFor.value = orderType;
    pickingCustomer.value = true;
    return;
  }

  // BR-064 — the guest count is its own setting, and a type can want one
  // without seating anybody. Ask, rather than send an order the server will
  // refuse for a number nobody was offered the chance to give.
  if (orderType.requires_cover_count) {
    countingType.value = orderType;
    covers.value = 2;
    return;
  }

  const created = await orders.create({
    order_type: orderType.name,
    pos_profile: session.profile!.name,
  });

  if (created) {
    pane.value = "items";
    await router.replace({ name: "order", params: { orderName: created } });
  }
}

// --------------------------------------------------------------------------
// Who the order is for (FR-2.1 step 4, D-050)
// --------------------------------------------------------------------------

const pickingCustomer = ref(false);

/**
 * The type waiting for a customer, when it cannot be opened without one.
 *
 * `null` means an order already exists and the picker is only changing who it
 * belongs to — the two paths end differently, so the difference is held here
 * rather than guessed from whether an order happens to be loaded.
 */
const customerFor = ref<OrderType | null>(null);

/** The type the picker is answering for: the one waiting, else the one in hand. */
const customerType = computed(() => customerFor.value ?? orderType.value);

/**
 * Show the address step.
 *
 * Inferred from `customer_mode`, because no order type carries a "requires an
 * address" flag — a type that insists on a customer is a type where the
 * customer's details are the point, which in a restaurant means delivery. The
 * step is skippable, so nothing is demanded that the server does not demand.
 */
const customerWithAddress = computed(() => customerType.value?.customer_mode === "required");

async function onCustomerPicked(payload: {
  customer: string;
  deliveryAddress: string | null;
}): Promise<void> {
  pickingCustomer.value = false;

  const waiting = customerFor.value;
  if (!waiting) {
    await orders.setCustomer(payload.customer, payload.deliveryAddress);
    return;
  }

  customerFor.value = null;
  const created = await orders.create({
    order_type: waiting.name,
    pos_profile: session.profile!.name,
    customer: payload.customer,
    delivery_address: payload.deliveryAddress,
  });

  if (!created) return;

  startupError.value = null;
  pane.value = "items";
  await router.replace({ name: "order", params: { orderName: created } });
}

async function onCustomerCleared(): Promise<void> {
  pickingCustomer.value = false;
  await orders.setCustomer(null, null);
}

/**
 * The type waiting for a guest count, when it wants one and seats nobody.
 *
 * `null` closes the prompt. Two is the opening guess: two is the commonest
 * party in any restaurant that counts covers at all.
 */
const countingType = ref<OrderType | null>(null);
const covers = ref(2);

async function confirmCovers(): Promise<void> {
  const orderType = countingType.value;
  if (!orderType || covers.value < 1) return;

  countingType.value = null;
  const created = await orders.create({
    order_type: orderType.name,
    pos_profile: session.profile!.name,
    cover_count: covers.value,
  });

  if (created) {
    pane.value = "items";
    await router.replace({ name: "order", params: { orderName: created } });
  }
}

/**
 * The type waiting for a table, when the cashier came here from **New**.
 *
 * `null` means the floor is just being looked at, and tapping a free table
 * seats whichever type this terminal uses for table service.
 */
const seatingType = ref<OrderType | null>(null);

/**
 * A table waiting for the cashier to say what kind of order to open on it.
 *
 * `null` means nothing is waiting. Set when tapping a free table could not
 * settle the type on its own — see `seat`.
 */
const pendingTable = ref<FloorTable | null>(null);

/**
 * Types this terminal would open *by* picking a table first.
 *
 * A hint, not the rule. `requires_table` answers "must a table be chosen
 * before the order opens" — a workflow question — and a restaurant that turns
 * it off still has tables and still seats people at them (FR-2.1a). So when it
 * settles the question it is used, and when it does not the cashier is asked.
 */
const tableTypes = computed(() => session.orderTypes.filter((type) => type.requires_table));

async function seat(table: FloorTable): Promise<void> {
  // A bill already in hand is almost always the one the cashier means to put
  // on this table — they rang items up and *then* decided where the customer
  // sits. Opening a second order here would take their work off the screen.
  if (orders.order && !orders.isClosed && !seatingType.value) {
    seatHere.value = table;
    return;
  }

  // One candidate is an answer. None — because no type demands a table — and
  // several are both guesses, and guessing here opens the wrong kind of order
  // on a real table.
  const type = seatingType.value ?? (tableTypes.value.length === 1 ? tableTypes.value[0] : null);

  if (!type) {
    pendingTable.value = table;
    pane.value = "new";
    return;
  }

  await openAt(table, type);
}

/**
 * The table tapped while an order was open, waiting for the cashier to say
 * which of the two things they meant (BR-061).
 */
const seatHere = ref<FloorTable | null>(null);

/** Put the order in hand on that table. */
async function seatCurrent(): Promise<void> {
  const table = seatHere.value;
  seatHere.value = null;
  if (!table) return;

  const done = await orders.seat(table.name);
  if (done) pane.value = "items";
}

/** Leave the order in hand open and start another one on that table. */
async function openAnotherHere(): Promise<void> {
  const table = seatHere.value;
  seatHere.value = null;
  if (!table) return;

  const type = tableTypes.value.length === 1 ? tableTypes.value[0] : null;
  if (type) await openAt(table, type);
  else {
    pendingTable.value = table;
    pane.value = "new";
  }
}

/** Open an order of this type, seated at this table. */
async function openAt(table: FloorTable, type: OrderType): Promise<void> {
  const created = await orders.create({
    order_type: type.name,
    pos_profile: session.profile!.name,
    table: table.name,
    cover_count: type.requires_cover_count ? table.capacity || 2 : null,
  });

  seatingType.value = null;
  pendingTable.value = null;
  if (created) {
    pane.value = "items";
    await router.replace({ name: "order", params: { orderName: created } });
  }
}

/**
 * Switch the screen to another open order without unmounting it.
 *
 * `router.replace` keeps the address honest — a reload lands on the order the
 * cashier is actually looking at — and the watch below does the reading.
 */
function switchTo(order: OpenOrder): void {
  openOrder(order.name);
}

function openOrder(orderName: string): void {
  pane.value = "items";
  if (orderName === orders.order?.order_name) return;
  void router.replace({ name: "order", params: { orderName } });
}

/** The screen never unmounts, so the address is what tells it to change. */
watch(
  () => route.fullPath,
  () => void startFromRoute(),
);


// --------------------------------------------------------------------------
// BR-044 — nothing goes on a bill without an open shift
// --------------------------------------------------------------------------

/**
 * Stop, and offer the way out.
 *
 * The server refuses this either way (`utils/order.assert_shift_open`); what
 * the screen adds is the reason and a button, instead of a raw error after the
 * item was already tapped. The tiles stay live on purpose — a greyed-out menu
 * explains nothing, and "why can I not sell" is the question being answered.
 *
 * `session.canSell` is the flag the server itself gates on — the
 * terminal's `restaurant_shift` — so the two cannot disagree.
 */
const askingForShift = ref(false);

function maySell(): boolean {
  if (session.canSell) return true;

  askingForShift.value = true;
  return false;
}

function openShiftFromNotice(): void {
  askingForShift.value = false;
  openingTill.value = true;
}

/**
 * The shift dialog closed — opened or abandoned, it does not say which.
 *
 * If a shift is open now and the screen is still showing the message that it
 * was not, the address never got what it asked for: create the order it was
 * sent here to create, rather than leaving the cashier looking at a complaint
 * about something they have just fixed.
 */
function onTillOpened(): void {
  openingTill.value = false;
  if (session.canSell && startupError.value) void startFromRoute();
}

/** FR-2.2 — an item with modifier groups opens the popup first. */
function onPick(item: CatalogItem, qty: number): void {
  if (!maySell()) return;

  // Nothing to put it on yet. Which type the order should be is a real question
  // — a table, a customer, a price list hang off it — so the tap opens **جديد**
  // rather than guessing one (D-056).
  if (!orders.order) {
    pane.value = "new";
    return;
  }

  if (item.modifier_groups.length) {
    // The quantity has to survive the detour, or six coffees with extra milk
    // arrive as one.
    pendingItem.value = item;
    pendingQty.value = qty;
    return;
  }
  void orders.addItem(item.item_code, { qty });
}

function onModifiersConfirmed(payload: { modifiers: ModifierChoice[]; notes: string }): void {
  const item = pendingItem.value;
  const qty = pendingQty.value;
  clearPending();
  if (!item) return;

  void orders.addItem(item.item_code, {
    qty,
    modifiers: payload.modifiers,
    notes: payload.notes || null,
  });
}

function clearPending(): void {
  pendingItem.value = null;
  pendingQty.value = 1;
}

function repeat(line: OrderLine): void {
  if (!maySell()) return;
  void orders.addItem(line.item, { qty: 1 });
}

/** Tapping a line opens everything known about it (06 Screen 3). */
const inspecting = ref<OrderLine | null>(null);

function inspect(line: OrderLine): void {
  inspecting.value = line;
}

/** Keep the open dialog pointing at the line as the order is re-read. */
watch(
  () => orders.lines,
  (lines) => {
    if (!inspecting.value) return;
    inspecting.value = lines.find((line) => line.idx === inspecting.value?.idx) ?? null;
  },
);

async function changeQty(idx: number, qty: number): Promise<void> {
  // The detail dialog closes first: two stacked dialogs both answer Escape,
  // and one key would dismiss both (D-049).
  if (!session.canSell) {
    inspecting.value = null;
    maySell();
    return;
  }

  await orders.setQty(idx, qty);
}

/** FR-2.9 — the dialog stays open: the cashier can see it took. */
async function changeLineNotes(idx: number, notes: string | null): Promise<void> {
  await orders.setLineNotes(idx, notes);
}

function voidFromDetail(line: OrderLine): void {
  inspecting.value = null;
  askVoid(line);
}

/**
 * FR-2.5 — the two are different acts, and only one asks a question.
 *
 * Before the ticket prints, a line coming off is a mis-tap: the customer said
 * rice and meant bulgur, or the finger landed one button over. Demanding a
 * written reason there costs seconds at every till and teaches cashiers to type
 * "x" to get past the box. Once the kitchen has it, the food is being made and
 * somebody has to answer for it.
 */
function askVoid(line: OrderLine): void {
  if (line.status === "pending") {
    void orders.removeLine(line.idx);
    return;
  }

  voidTarget.value = line;
  voidReason.value = "";
}

async function confirmVoid(): Promise<void> {
  const line = voidTarget.value;
  if (!line || !voidReason.value.trim()) return;

  voidTarget.value = null;
  await orders.voidLine(line.idx, voidReason.value.trim());
}

async function confirmCancel(): Promise<void> {
  if (!cancelReason.value.trim()) return;

  const done = await orders.cancel(cancelReason.value.trim());
  cancelling.value = false;
  if (done) await router.push({ name: "home" });
}

// --------------------------------------------------------------------------
// The action row (06 Screen 3, D-037)
// --------------------------------------------------------------------------

/**
 * What a cashier reaches for without looking. Kept short on purpose: the row
 * has to stay one line at 1280px and shrink cleanly when a permission removes
 * an entry.
 */
const rowActions = computed<OrderAction[]>(() => [
  {
    key: "kitchen",
    label: "order.sendToKitchen",
    icon: "kitchen",
    disabled: locked.value || !orders.hasUnsent,
  },
  {
    // FR-2.9 — the note every station reads. In the row, not the menu: an
    // allergy is not something to go looking for.
    key: "notes",
    label: "note.orderAction",
    icon: "note",
    disabled: locked.value,
  },
  {
    key: "refresh",
    label: "action.refresh",
    icon: "refresh",
    disabled: orders.busy,
  },
]);

/**
 * Everything else, one deliberate tap further away.
 *
 * Cancelling is here rather than in the row because the row is where a busy
 * hand lands without looking, and this one cannot be taken back.
 */
const moreActions = computed<OrderAction[]>(() => {
  const entries: OrderAction[] = [];

  // D-038 — offered only where a conversion is possible at all: an app order
  // is billed to the platform and can never become a walk-in sale.
  if (session.can("can_change_order_type") && orderType.value?.counterparty === "walk_in") {
    entries.push({
      key: "convert",
      label: "convert.action",
      icon: "swap",
      disabled: locked.value,
    });
  }

  // FR-2.11 — a name to shout, not a Customer. In the menu rather than the
  // row: most orders never need one.
  entries.push({
    key: "callName",
    label: "call.action",
    icon: "user",
    disabled: locked.value,
  });

  // FR-2.1 step 4 — a real Customer, with a number and an address. Not offered
  // on a type that decides its own: an app order is billed to the platform, and
  // the server refuses to change it (D-038).
  if (orderType.value?.customer_mode !== "pre_set") {
    entries.push({
      key: "customer",
      label: orders.order?.customer ? "customer.change" : "customer.action",
      icon: "users",
      disabled: locked.value,
    });
  }

  if (session.can("can_cancel_order")) {
    entries.push({
      key: "cancel",
      label: "order.cancelOrder",
      icon: "ban",
      disabled: locked.value,
      destructive: true,
    });
  }

  return entries;
});

function onAction(action: OrderAction): void {
  if (action.key === "kitchen") void send();
  else if (action.key === "refresh") void reload();
  else if (action.key === "notes") openNotes();
  else if (action.key === "callName") openCallName();
  else if (action.key === "customer") pickingCustomer.value = true;
  else if (action.key === "convert") converting.value = true;
  else if (action.key === "cancel") cancelling.value = true;
}

// --------------------------------------------------------------------------
// The name to call out (FR-2.11)
// --------------------------------------------------------------------------

const editingCallName = ref(false);
const draftCallName = ref("");

function openCallName(): void {
  draftCallName.value = orders.order?.call_name ?? "";
  editingCallName.value = true;
}

async function saveCallName(): Promise<void> {
  editingCallName.value = false;
  await orders.setCallName(draftCallName.value.trim() || null);
}

// --------------------------------------------------------------------------
// The order's own note (FR-2.9)
// --------------------------------------------------------------------------

const editingNotes = ref(false);
const draftNotes = ref("");

function openNotes(): void {
  draftNotes.value = orders.order?.notes ?? "";
  editingNotes.value = true;
}

async function saveNotes(): Promise<void> {
  editingNotes.value = false;
  await orders.setNotes(draftNotes.value.trim() || null);
}

// --------------------------------------------------------------------------
// Changing the type (D-038)
// --------------------------------------------------------------------------

const converting = ref(false);

async function convert(orderType: string, coverCount: number | null): Promise<void> {
  converting.value = false;
  await orders.changeType(orderType, { coverCount });
}

/**
 * A type that seats people needs a table, and the dialog is not a floor plan.
 *
 * The floor plan is told which order is being converted, so it seats this one
 * instead of opening a second.
 */
function convertWithTable(orderType: string): void {
  converting.value = false;
  if (!orders.order) return;

  void router.push({
    name: "tables",
    params: { orderType },
    query: { convert: orders.order.order_name },
  });
}

/** Another till may have added to this order; re-read rather than guess. */
async function reload(): Promise<void> {
  if (orders.order) await orders.open(orders.order.order_name);
}

function goToPayment(): void {
  if (!orders.order) return;
  void router.push({ name: "payment", params: { orderName: orders.order.order_name } });
}

async function send(): Promise<void> {
  await orders.sendToKitchen();
}
</script>

<template>
  <!--
    No title bar. A till screen is read from across a counter, and ninety pixels
    of chrome repeating what the bill already says is ninety pixels of menu the
    cashier does not get. Everything that lived up there has a better home: the
    order's number, state, type and customer are on the bill; the way back is
    the button beside the tabs.
  -->
  <main class="grid h-full grid-rows-[minmax(0,1fr)] bg-background">
    <div class="grid min-h-0 grid-rows-[minmax(0,1fr)] p-5">
      <!--
        Two columns while a bill is in hand, one when there is not: the working
        column is the screen either way, and stretching it over the whole width
        with nothing beside it is better than a permanent empty half.
      -->
      <!--
        Two columns, always. The till looks the same whether a bill is in hand
        or not (D-056) — a screen that changes shape between customers is a
        screen a cashier has to re-read, and the empty panel says what to do
        next in the place the bill will appear.
      -->
      <div class="grid min-h-0 gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <!--
          A column, not a row template. The notices below are `empty:hidden`, so
          on a quiet screen they are not a grid item at all — and every child
          after them slid up a row: the menu took the `auto` track and the nav
          took `minmax(0, 1fr)`, which stretched it to 374px. It came right
          again the moment an error appeared, which is why it looked like the
          bar changed size on its own.

          Flex asks each child what it wants instead of counting them, so the
          pane grows and the two bars keep their own height whatever is on
          screen.
        -->
        <div class="flex min-h-0 flex-col gap-3">
          <!-- What the order can do. Where the cashier goes is the bar along
               the bottom; the two never mix (D-042). Nothing in hand, nothing
               to act on — the row is not drawn rather than drawn all disabled. -->
          <OrderActionBar
            v-if="orders.order"
            :actions="rowActions"
            :more="moreActions"
            @select="onAction"
          />

          <div class="flex flex-col gap-2 empty:hidden">
            <!--
              BR-044 — visible for as long as it is true, and it carries the way
              out (D-055). The screen is not locked: the cashier can still read
              the floor and yesterday's bills. What a closed drawer stops is
              money moving, and that stop lands on the tap that moves it.

              This also replaces the till screen's shift badge, which went with
              that screen — and says more, because it says nothing at all while
              a shift is open.
            -->
            <button
              v-if="!session.canSell"
              type="button"
              class="flex min-h-tap items-center justify-between gap-3 rounded-rpos bg-status-reserved/10 px-3 text-sm font-semibold text-status-reserved transition duration-200 ease-rpos hover:bg-status-reserved/20"
              @click="askingForShift = true"
            >
              <span class="flex items-center gap-2">
                <AppIcon
                  name="card"
                  :size="18"
                />
                {{ t("home.shiftClosed") }}
              </span>
              <span class="underline">{{ t("shift.openTill") }}</span>
            </button>

            <p
              v-if="startupError"
              role="alert"
              class="rounded-rpos bg-danger/10 p-3 text-sm text-danger"
            >
              {{ startupError }}
            </p>

            <p
              v-if="orders.error"
              role="alert"
              class="rounded-rpos bg-danger/10 p-3 text-sm text-danger"
            >
              {{ orders.error }}
            </p>

            <!-- 09 §10 — an order carrying queued work must say so, or the
                 cashier reads a confirmation the server never got. -->
            <p
              v-if="orders.pendingSync"
              role="status"
              class="flex items-center gap-2 rounded-rpos bg-status-cleaning/10 p-3 text-sm text-status-cleaning"
            >
              <AppIcon
                name="hourglass"
                :size="18"
              />
              {{ t("order.pendingSync") }}
            </p>

            <p
              v-if="orders.unrouted.length"
              role="status"
              class="rounded-rpos bg-status-reserved/10 p-3 text-sm text-status-reserved"
            >
              {{ t("order.notRouted", { items: orders.unrouted.join(t("common.listSeparator")) }) }}
            </p>
          </div>

          <div
            v-if="pane === 'items'"
            class="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)] rounded-rpos bg-surface p-4 shadow-card"
          >
            <ItemPicker
              :order-type="orderType"
              :disabled="pickerDisabled"
              @pick="onPick"
            />
          </div>

          <!-- The same list as the till screen, in the same component: one
               place decides what an order looks like. Here it can also be asked
               for drafts and for today's history (D-042). -->
          <OpenOrdersPanel
            v-else-if="pane === 'orders'"
            v-model:layout="floorLayout"
            v-model:search="floorSearch"
            v-model:sort="floorSort"
            class="min-h-0 flex-1"
            :orders="floorOrders"
            :loading="floorLoading"
            :error="floorError"
            :searching="floorSearching"
            :scope="floorMaySeeEveryone ? floorScope : null"
            :view="floorView"
            @open="switchTo"
            @floor-plan="pane = 'tables'"
            @update:scope="floorScope = $event"
            @update:view="floorView = $event"
          />

          <FloorPane
            v-else-if="pane === 'tables'"
            class="min-h-0 flex-1"
            @seat="seat"
            @open="openOrder"
          />

          <NewOrderPane
            v-else
            class="min-h-0 flex-1"
            :seating="pendingTable?.table_number ?? null"
            @open="startAnother"
          />

          <!-- Under the working column, so the bill beside it keeps the full
               height of the screen (06 Screen 3). -->
          <!-- `relative` anchors the menu sheet above the bar. -->
          <div class="relative">
            <ShiftMenu
              :open="menuOpen"
              @select="onMenu"
              @close="menuOpen = false"
            />

            <OrderBottomNav
              :entries="navEntries"
              :active="menuOpen ? 'menu' : pane"
              @select="onNavigate"
            />
          </div>
        </div>

        <!-- Where the bill will be. Not a blank space: the one thing to do
             from here is start an order, so that is the button. -->
        <section
          v-if="!orders.order"
          class="grid place-content-center place-items-center gap-3 rounded-rpos bg-surface p-8 text-center shadow-card"
        >
          <span class="text-muted opacity-30">
            <AppIcon
              name="receipt"
              :size="52"
            />
          </span>
          <p class="text-muted">
            {{ t("panel.noOrder") }}
          </p>
          <button
            type="button"
            class="flex min-h-tap items-center gap-2 rounded-rpos bg-primary px-6 font-bold text-primary-contrast shadow-card transition duration-200 ease-rpos hover:shadow-lift"
            @click="pane = 'new'"
          >
            <AppIcon
              name="plus"
              :size="20"
            />
            {{ t("home.newOrder") }}
          </button>
        </section>

        <!-- BR-044 — the Pay button obeys the same rule as the item tap: a
             drawer that has been counted takes no more money (D-055). -->
        <OrderPanel
          v-else
          :order="orders.order"
          :lines="orders.lines"
          :busy="locked"
          :can-pay="!locked && !orders.isEmpty && session.canSell"
          @void="askVoid"
          @repeat="repeat"
          @inspect="inspect"
          @pay="goToPayment"
        />
      </div>
    </div>

    <!-- The only way out of the app, so it asks first (D-055). -->
    <BaseDialog
      :open="signingOut"
      :title="t('home.logoutConfirm')"
      :dismissible="true"
      @close="signingOut = false"
    >
      <p class="mb-4 text-sm text-muted">
        {{ t("home.logoutBody") }}
      </p>
      <div class="flex gap-2">
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos border border-line"
          @click="signingOut = false"
        >
          {{ t("action.undo") }}
        </button>
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-danger font-medium text-white"
          @click="signOut"
        >
          {{ t("home.logout") }}
        </button>
      </div>
    </BaseDialog>

    <!-- FR-2.11 — written on the ticket so the counter knows who to call. -->
    <BaseDialog
      :open="editingCallName"
      :title="t('call.title')"
      :dismissible="true"
      @close="editingCallName = false"
    >
      <p class="mb-3 text-sm text-muted">
        {{ t("call.body") }}
      </p>

      <input
        v-model="draftCallName"
        type="text"
        class="mb-4 min-h-tap w-full rounded-rpos border border-line bg-background px-3 text-lg"
        :placeholder="t('call.placeholder')"
        @keyup.enter="saveCallName"
      >

      <div class="flex gap-2">
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos border border-line"
          @click="editingCallName = false"
        >
          {{ t("action.undo") }}
        </button>
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-primary font-medium text-primary-contrast disabled:opacity-40"
          :disabled="orders.busy"
          @click="saveCallName"
        >
          {{ t("action.save") }}
        </button>
      </div>
    </BaseDialog>

    <!-- FR-2.9 — printed on the header of every station's ticket. -->
    <BaseDialog
      :open="editingNotes"
      :title="t('note.orderTitle')"
      :dismissible="true"
      @close="editingNotes = false"
    >
      <p class="mb-3 text-sm text-muted">
        {{ t("note.orderBody") }}
      </p>

      <NoteEditor
        v-model="draftNotes"
        class="mb-4"
        scope="order"
      />

      <div class="flex gap-2">
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos border border-line"
          @click="editingNotes = false"
        >
          {{ t("action.undo") }}
        </button>
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-primary font-medium text-primary-contrast disabled:opacity-40"
          :disabled="orders.busy"
          @click="saveNotes"
        >
          {{ t("action.save") }}
        </button>
      </div>
    </BaseDialog>

    <!--
      BR-061 — two honest readings of one tap, so neither is guessed. The order
      in hand is never closed by either answer: "another order" leaves it open
      under الطلبات, the way New does.
    -->
    <BaseDialog
      :open="Boolean(seatHere)"
      :title="t('tables.seatTitle', { number: seatHere?.table_number ?? '' })"
      :dismissible="true"
      @close="seatHere = null"
    >
      <p class="mb-4 text-sm text-muted">
        {{ t("tables.seatBody") }}
      </p>

      <div class="flex flex-col gap-2">
        <button
          type="button"
          class="min-h-tap w-full rounded-rpos bg-primary font-medium text-primary-contrast disabled:opacity-40"
          :disabled="orders.busy"
          @click="seatCurrent"
        >
          {{ t("tables.seatCurrent") }}
        </button>
        <button
          type="button"
          class="min-h-tap w-full rounded-rpos border border-line font-medium"
          :disabled="orders.busy"
          @click="openAnotherHere"
        >
          {{ t("tables.seatNew") }}
        </button>
        <button
          type="button"
          class="min-h-tap w-full rounded-rpos text-muted"
          @click="seatHere = null"
        >
          {{ t("action.undo") }}
        </button>
      </div>
    </BaseDialog>

    <!-- BR-064 — only where the order type asks for it (FR-2.1a). -->
    <BaseDialog
      :open="Boolean(countingType)"
      :title="t('covers.title')"
      :dismissible="true"
      @close="countingType = null"
    >
      <p class="mb-4 text-sm text-muted">
        {{ t("covers.body") }}
      </p>

      <div class="mb-5 flex items-center justify-center gap-4">
        <button
          type="button"
          class="grid h-14 w-14 place-items-center rounded-full bg-background text-muted transition duration-200 ease-rpos hover:bg-primary/10 hover:text-primary disabled:opacity-40"
          :disabled="covers <= 1"
          :aria-label="t('picker.qtyLess')"
          @click="covers = Math.max(1, covers - 1)"
        >
          <AppIcon
            name="minus"
            :size="24"
          />
        </button>

        <span class="rpos-numeric w-16 text-center text-3xl font-bold">{{
          formatNumber(covers)
        }}</span>

        <button
          type="button"
          class="grid h-14 w-14 place-items-center rounded-full bg-background text-muted transition duration-200 ease-rpos hover:bg-primary/10 hover:text-primary"
          :aria-label="t('picker.qtyMore')"
          @click="covers = covers + 1"
        >
          <AppIcon
            name="plus"
            :size="24"
          />
        </button>
      </div>

      <div class="flex gap-2">
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos border border-line"
          @click="countingType = null"
        >
          {{ t("action.undo") }}
        </button>
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-primary font-medium text-primary-contrast disabled:opacity-40"
          :disabled="orders.busy"
          @click="confirmCovers"
        >
          {{ t("home.newOrder") }}
        </button>
      </div>
    </BaseDialog>

    <!--
      BR-044 — the stop, and the way past it. Two buttons and no more: the
      cashier tapped an item and wants to keep selling, not read a page.
      Opening a shift is offered only to whoever may (D-053).
    -->
    <BaseDialog
      :open="askingForShift"
      :title="t('home.shiftClosed')"
      :dismissible="true"
      @close="askingForShift = false"
    >
      <p class="mb-4 text-sm text-muted">
        {{ t("home.shiftRequired") }}
      </p>

      <div class="flex gap-2">
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos border border-line"
          @click="askingForShift = false"
        >
          {{ t("action.undo") }}
        </button>
        <button
          v-if="session.can('can_open_shift')"
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-primary font-bold text-primary-contrast"
          @click="openShiftFromNotice"
        >
          {{ t("shift.openTill") }}
        </button>
      </div>
    </BaseDialog>

    <!-- FR-2.1 step 4 — found by number, created from the same box (D-050). -->
    <CustomerDialog
      :open="pickingCustomer"
      :customer="orders.order?.customer ?? null"
      :with-address="customerWithAddress"
      :required="customerType?.customer_mode === 'required'"
      @close="pickingCustomer = false"
      @select="onCustomerPicked"
      @clear="onCustomerCleared"
    />

    <OpenTillDialog
      :open="openingTill"
      @close="onTillOpened"
    />

    <CloseTillDialog
      :open="closingTill"
      :settlement-required="Boolean(shift.state?.settlement_required)"
      @close="closingTill = false"
    />

    <CloseDayDialog
      :open="closingDay"
      @close="closingDay = false"
    />

    <LineDetailDialog
      :line="inspecting"
      :busy="locked"
      @close="inspecting = null"
      @set-qty="changeQty"
      @set-notes="changeLineNotes"
      @void="voidFromDetail"
    />

    <OrderTypeChangeDialog
      v-if="orders.order"
      :open="converting"
      :order-name="orders.order.order_name"
      :current-type="orders.order.order_type"
      :cover-count="orders.order.cover_count"
      :busy="orders.busy"
      @close="converting = false"
      @confirm="convert"
      @pick-table="convertWithTable"
    />

    <ModifierDialog
      :item="pendingItem"
      @confirm="onModifiersConfirmed"
      @cancel="clearPending"
    />

    <!-- BR-013: a reason is mandatory, so this cannot be dismissed away. -->
    <BaseDialog
      :open="Boolean(voidTarget)"
      :title="t('order.voidReason')"
      :dismissible="true"
      @close="voidTarget = null"
    >
      <p class="mb-3 text-sm text-muted">
        {{ voidTarget?.item_name }}
      </p>
      <input
        v-model="voidReason"
        type="text"
        class="mb-4 min-h-tap w-full rounded-rpos border border-line bg-background px-3"
        :placeholder="t('order.voidPlaceholder')"
      >
      <div class="flex gap-2">
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos border border-line"
          @click="voidTarget = null"
        >
          {{ t("action.undo") }}
        </button>
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-danger font-medium text-white disabled:opacity-50"
          :disabled="!voidReason.trim()"
          @click="confirmVoid"
        >
          {{ t("order.voidItem") }}
        </button>
      </div>
    </BaseDialog>

    <BaseDialog
      :open="cancelling"
      :title="t('order.cancelOrder')"
      @close="cancelling = false"
    >
      <p class="mb-3 text-sm text-muted">
        {{ t("order.cancelBody") }}
      </p>
      <input
        v-model="cancelReason"
        type="text"
        class="mb-4 min-h-tap w-full rounded-rpos border border-line bg-background px-3"
        :placeholder="t('order.voidReason')"
      >
      <div class="flex gap-2">
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos border border-line"
          @click="cancelling = false"
        >
          {{ t("action.undo") }}
        </button>
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-danger font-medium text-white disabled:opacity-50"
          :disabled="!cancelReason.trim()"
          @click="confirmCancel"
        >
          {{ t("order.confirmCancel") }}
        </button>
      </div>
    </BaseDialog>
  </main>
</template>

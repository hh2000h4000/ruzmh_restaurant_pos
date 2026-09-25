<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { recordView } from "@/api/activity";
import { whatOpens, type ModifierChoice, type OpenOrder, type OrderLine } from "@/api/order";
import { reprintReceipt } from "@/api/printing";
import AppIcon from "@/components/AppIcon.vue";
import AppToast from "@/components/AppToast.vue";
import BaseDialog from "@/components/BaseDialog.vue";
import CouponDialog from "@/components/order/CouponDialog.vue";
import CustomerDialog from "@/components/order/CustomerDialog.vue";
import ItemPicker from "@/components/order/ItemPicker.vue";
import LineDetailDialog from "@/components/order/LineDetailDialog.vue";
import ModifierDialog from "@/components/order/ModifierDialog.vue";
import OrderActionBar, { type OrderAction } from "@/components/order/OrderActionBar.vue";
import NoteEditor from "@/components/order/NoteEditor.vue";
import OrderPanel from "@/components/order/OrderPanel.vue";
import OrderTypeChangeDialog from "@/components/order/OrderTypeChangeDialog.vue";
import ReasonDialog from "@/components/order/ReasonDialog.vue";
import RefundDialog from "@/components/order/RefundDialog.vue";
import ActivityDialog from "@/components/order/ActivityDialog.vue";
import JoinBillDialog from "@/components/order/JoinBillDialog.vue";
import JoinTablesDialog from "@/components/order/JoinTablesDialog.vue";
import SplitBillDialog from "@/components/order/SplitBillDialog.vue";
import UnprintedTickets from "@/components/order/UnprintedTickets.vue";
import ReturnDialog from "@/components/order/ReturnDialog.vue";
import CloseDayDialog from "@/components/shift/CloseDayDialog.vue";
import CloseTillDialog from "@/components/shift/CloseTillDialog.vue";
import DrawerCashDialog from "@/components/shift/DrawerCashDialog.vue";
import GiftCardSellDialog from "@/components/shift/GiftCardSellDialog.vue";
import TillReportDialog from "@/components/shift/TillReportDialog.vue";
import OpenTillDialog from "@/components/shift/OpenTillDialog.vue";
import RosterDialog from "@/components/shift/RosterDialog.vue";
import ShiftMenu from "@/components/shift/ShiftMenu.vue";
import FloorPane from "@/components/order/FloorPane.vue";
import NewOrderPane from "@/components/order/NewOrderPane.vue";
import ReservationsPane from "@/components/order/ReservationsPane.vue";
import { seatReservation } from "@/api/reservation";
import OrderBottomNav, { type NavEntry } from "@/components/order/OrderBottomNav.vue";
import OpenOrdersPanel from "@/components/pos/OpenOrdersPanel.vue";
import {
  IDLE,
  NO_BRAND,
  toDisplayState,
  useCustomerDisplayPublisher,
  type Brand,
} from "@/composables/useCustomerDisplay";
import { useDismiss } from "@/composables/useDismiss";
import { useOpenOrders } from "@/composables/useOpenOrders";
import { formatNumber, t, tn } from "@/i18n";
import { isMissingScreen } from "@/router/missingScreen";
import { useAuthStore } from "@/stores/auth";
import { useOrderStore } from "@/stores/order";
import { useSessionStore } from "@/stores/session";
import { useNoticeStore } from "@/stores/notice";
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
const cancelling = ref(false);

const orderType = computed(
  () => session.orderTypes.find((type) => type.name === orders.order?.order_type) ?? null,
);

/**
 * Nothing on this bill may change.
 *
 * A closed shift is deliberately **not** in here (D-058). Greying every control
 * out would say "no" everywhere and explain nowhere; the shift is answered at
 * the tap instead, by whichever action needed it, with the button that fixes it
 * attached. If a cashier managed to add an item, the shift was open — so the
 * screen never needs to say so standing still.
 */
const locked = computed(() => orders.busy || orders.isClosed);

// --------------------------------------------------------------------------
// The screen facing the guest (FR-13, D-162)
// --------------------------------------------------------------------------

const customerDisplay = useCustomerDisplayPublisher();

/**
 * The restaurant's name, for the screen that has no session to read it from.
 *
 * The display window asks the server for nothing, so its stores are empty — the
 * till is the only one of the two that knows what the place is called.
 */
function house(): Brand {
  return {
    house: session.data?.branch?.branch ?? session.profile?.name ?? "",
    // Both come from the server with everything else, so the screen keeps them
    // through an outage like it keeps the menu (`D-202`).
    logo: session.data?.theme?.brand_logo ?? null,
    message: session.data?.customer_display?.message ?? "",
    banners: session.data?.customer_display?.banners ?? [],
    seconds: session.data?.customer_display?.seconds ?? NO_BRAND.seconds,
  };
}

/**
 * Push the bill to the second screen on every change to it.
 *
 * A watcher rather than a call beside each action: there are a dozen ways a
 * line reaches the bill — tapped, repeated, split, joined, voided, re-priced by
 * an order-type change — and a condition remembered in a dozen places is one
 * eleven of them get right (`CLAUDE.md` §5.5). The store is what they all end
 * at, so it is what is watched.
 *
 * A paid bill turns the screen into the guest's number rather than blanking it:
 * that is the moment they are waiting to be told something (`FR-2.10`).
 */
watch(
  [() => orders.order, () => orders.lines],
  () => {
    if (!orders.order) {
      customerDisplay.publish({ ...IDLE, ...house() });
      return;
    }

    const state = toDisplayState(orders.order, orders.lines, house());
    customerDisplay.publish(
      orders.isClosed ? { ...state, mode: "thanks" as const, lines: [] } : state,
    );
  },
  { deep: true, immediate: true },
);

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
    if (existing !== orders.order?.order_name) {
      // A type that sends on save sends as it is put down (`D-223`).
      await orders.putDown();
      // Put the previous bill down before picking this one up (`D-106`).
      // Neither event changes anything, so the server cannot infer either —
      // and "who had this bill open" is a question asked about a bill that
      // came out wrong.
      noteView(orders.order?.order_name ?? null, "left");
      await orders.open(existing);
      noteView(existing, "viewed");
    }
    return;
  }

  const typeName = route.params.orderType as string | undefined;
  if (!typeName) {
    // The resting state is the **menu**, not a list of orders (D-056). A till
    // that opens on a list looks like a filing cabinet; the cashier's job is in
    // front of them, and the list is one tap away in the bar.
    // `?pane=new` is how the payment screen says "straight into the next one".
    await orders.putDown();
    orders.clear();
    pane.value = route.query.pane === "new" ? "new" : "items";
    return;
  }

  const type = session.orderTypes.find((candidate) => candidate.name === typeName);
  if (!type) {
    startupError.value = t("order.typeUnavailable");
    return;
  }

  await orders.putDown();
  orders.clear();
  // Where the cashier lands if the type cannot open right now — a closed shift,
  // a table to pick, a customer to find. Never the menu pane with no bill under
  // it, which is a wall of buttons that do nothing.
  pane.value = "new";
  await startAnother(type);
}

/**
 * Record that a bill was picked up or put down, and never get in the way.
 *
 * Fire-and-forget on purpose: this is bookkeeping, and a cashier must not wait
 * on it or be shown an error from it. The same trade the server side makes.
 */
function noteView(orderName: string | null, action: "viewed" | "left"): void {
  if (!orderName) return;
  void recordView(orderName, action).catch(() => {});
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
  older: floorOlder,
  searchOlder: floorSearchOlder,
  searchingOlder: floorSearchingOlder,
  search: floorSearch,
  searching: floorSearching,
  sort: floorSort,
  staleAt: floorStaleAt,
  carriedCount: floorCarriedCount,
  includeCarried: floorIncludeCarried,
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
  // would seat the next type the cashier taps for an unrelated reason. The same
  // is true of an item tapped before there was a bill: a cashier who goes to
  // the floor instead of answering **جديد** has changed their mind, and a dish
  // arriving on whatever bill they open next is worse than no dish.
  if (key !== "new") {
    pendingTable.value = null;
    pendingReservation.value = null;
    waitingPick.value = null;
  }

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

/**
 * The sheet closes when the cashier turns back to the bill.
 *
 * The anchor holds the bar as well as the sheet, because the bar's last entry is
 * the toggle: outside it, and the tap that opened the sheet would close it again
 * on its way up to the document.
 */
const menuAnchor = useDismiss(menuOpen);

const openingTill = ref(false);
const closingTill = ref(false);
/** The X report on screen; printing it is a button inside (`D-237`). */
const viewingReport = ref(false);
const movingCash = ref(false);
const sellingGiftCard = ref(false);
const closingDay = ref(false);

function onMenu(key: string): void {
  menuOpen.value = false;

  if (key === "openTill") openingTill.value = true;
  else if (key === "closeTill") closingTill.value = true;
  else if (key === "closeDay") closingDay.value = true;
  else if (key === "logout") signingOut.value = true;
  else if (key === "clock") void punchClock();
  else if (key === "roster") showingRoster.value = true;
  else if (key === "customerDisplay") openCustomerDisplay();
  else if (key === "viewReport") viewingReport.value = true;
  else if (key === "drawerCash") movingCash.value = true;
  else if (key === "sellGiftCard") sellingGiftCard.value = true;
  // D-191 — a pane like the bar's own, reached from the menu because the bar
  // had no room for a sixth. Through `onNavigate`, so walking to it cancels a
  // table or a booking waiting for its order type, exactly as the bar does.
  else if (key === "reservations") onNavigate("reservations");
}

/**
 * Open the guest's screen in a window of its own (`FR-13.3`, `D-162`).
 *
 * A window rather than a tab, so it can be dragged to the second monitor and
 * left there — which is the whole arrangement. Named, so pressing the entry
 * again focuses the one already open instead of stacking a second.
 *
 * No error path: a blocked pop-up is the browser telling the person at the
 * keyboard something, and there is nothing the till can do about it that the
 * browser has not already said.
 */
function openCustomerDisplay(): void {
  window.open("/restaurant-pos/customer-display", "rpos-customer-display");
}

/**
 * `FR-8.4` — start or end this person's working time, from the till.
 *
 * No confirmation. A clock-in is one tap by design, and the direction is
 * decided by the server from the last punch — the screen only asks; a second
 * press in the same direction comes back refused rather than writing a shift
 * whose length cannot be computed.
 *
 * **Clocking out ends the session** (`D-179`). It is the same rule the welcome
 * screen follows: a punch leads where it means, and going home means leaving
 * the till — not standing at it with "تسجيل حضور" now drawn under the finger
 * that just tapped "تسجيل انصراف". The drawer is already counted by the time
 * this entry appears (`D-177`), so there is nothing left here for them.
 */
async function punchClock(): Promise<void> {
  const auth = useAuthStore();
  const arriving = auth.punchOnOffer === "in";

  await auth.punch(session.profile?.name ?? null);
  if (auth.error) {
    orders.error = auth.error;
    return;
  }

  if (!arriving) await signOut();
}

/** Confirmed, because signing out by accident mid-rush is a real annoyance. */
const signingOut = ref(false);
const showingLog = ref(false);

/**
 * Whose story the log is showing (`D-172`).
 *
 * Usually the bill in the till. But a refund's story lives on the bill it
 * reverses — that is where `return_created` is written — and the refund sheet
 * has to be able to reach it. **It could not**: the sheet replaced the old
 * behaviour of opening the sale (`D-171`), and the sale was the only route to
 * the timeline, so closing one hole opened another.
 */
const logFor = ref<{ orderName: string; number: number } | null>(null);

function showLogFor(orderName: string, number: number): void {
  logFor.value = { orderName, number };
  showingLog.value = true;
}
const showingRoster = ref(false);

async function signOut(): Promise<void> {
  // **Stays inside the app** (`D-098`). This used to hand the browser to
  // `/api/method/logout` and let Frappe redirect, which was right while Frappe
  // owned the login screen. It does not any more (`D-094`): that endpoint
  // answers with raw JSON and a `home_page` of `/login`, so a cashier signing
  // out landed on a page of braces — and behind it, the ERPNext login form the
  // PIN pad exists to replace.
  signingOut.value = false;
  await useAuthStore().signOut();
  await router.push({ name: "sign-in" });
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

  // A booking waiting for its kind of order (`D-191`) — the same question the
  // floor asks for a tapped table, answered by the same buttons.
  const booked = pendingReservation.value;
  if (booked) {
    await seatWith(booked.name, orderType);
    return;
  }

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

  await openBill({ order_type: orderType.name, pos_profile: session.profile!.name });
}

/**
 * Open a bill, and land the cashier on it.
 *
 * The tail of **every** way a bill can start — from *New*, from a table, from
 * the customer box, from the guest count — and it was written out four times.
 * Whatever the question was, the answer ends the same way: the bill exists, the
 * menu is in front of the cashier, and the address names it so a reload comes
 * back to the bill rather than to an empty till.
 *
 * Clearing `startupError` is part of that ending and was in only one of the
 * four: a type that could not be opened left its message on screen under the
 * bill that opened a moment later.
 */
async function openBill(payload: Parameters<typeof orders.create>[0]): Promise<void> {
  const created = await orders.create(payload);
  if (!created) return;

  startupError.value = null;
  pane.value = "items";
  await router.replace({ name: "order", params: { orderName: created } });
}

// --------------------------------------------------------------------------
// Who the order is for (FR-2.1 step 4, D-050)
// --------------------------------------------------------------------------

const pickingCustomer = ref(false);
const enteringCoupon = ref(false);

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
  await openBill({
    order_type: waiting.name,
    pos_profile: session.profile!.name,
    customer: payload.customer,
    delivery_address: payload.deliveryAddress,
  });
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
  await openBill({
    order_type: orderType.name,
    pos_profile: session.profile!.name,
    cover_count: covers.value,
  });
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

/**
 * A booking waiting for the cashier to say which kind of order to open for it
 * (`D-191`). Only when the terminal has more than one type that seats people —
 * the same condition, and the same pane, as a tapped table.
 */
const pendingReservation = ref<{ name: string; tableNumber: string | null } | null>(null);

/**
 * The party that booked has arrived (`FR-14.3`).
 *
 * **One way in, from the floor and from the list alike.** Both hand the booking
 * here, so which kind of order opens — and how the cashier is asked when the
 * terminal has several — is decided once, by the rule a tapped table already
 * follows.
 */
async function seatBooking(name: string, tableNumber: string | null): Promise<void> {
  if (!maySell()) return;

  const type = tableTypes.value.length === 1 ? tableTypes.value[0] : null;
  if (!type) {
    pendingReservation.value = { name, tableNumber };
    pane.value = "new";
    return;
  }

  await seatWith(name, type);
}

async function seatWith(name: string, type: OrderType): Promise<void> {
  pendingReservation.value = null;
  try {
    const seated = await seatReservation({
      name,
      pos_profile: session.profile!.name,
      order_type: type.name,
    });
    openOrder(seated.order_name);
  } catch (cause) {
    orders.error = cause instanceof Error ? cause.message : String(cause);
  }
}

/** Open an order of this type, seated at this table. */
async function openAt(table: FloorTable, type: OrderType): Promise<void> {
  await openBill({
    order_type: type.name,
    pos_profile: session.profile!.name,
    table: table.name,
    cover_count: type.requires_cover_count ? table.capacity || 2 : null,
  });

  // Cleared whether the bill opened or not: the question has been answered
  // either way, and a table left "waiting" would seat the next type tapped.
  seatingType.value = null;
  pendingTable.value = null;
}

/**
 * Switch the screen to another open order without unmounting it.
 *
 * `router.replace` keeps the address honest — a reload lands on the order the
 * cashier is actually looking at — and the watch below does the reading.
 */
function switchTo(order: OpenOrder): void {
  // Which document this row is, decided in `api/order` where it can be tested:
  // breaking it here left every test green (`D-171`).
  const target = whatOpens(order);

  if (target.kind === "queued") {
    orders.error = t("offline.queuedSale");
    return;
  }

  if (target.kind === "refund") {
    refundOpen.value = target.creditNote;
    return;
  }

  openOrder(target.orderName);
}

/** The credit note being looked at, or `null` (`D-171`). */
const refundOpen = ref<string | null>(null);

/**
 * The bill as a sheet, below a landscape tablet (`D-193`) — open, or folded into
 * the bar. Closed by a tap outside it or by Escape, like every popover (`D-176`).
 */
const billOpen = ref(false);
const billAnchor = useDismiss(billOpen);

function openOrder(orderName: string): void {
  pane.value = "items";
  if (orderName === orders.order?.order_name) return;
  void router.replace({ name: "order", params: { orderName } });
}

/**
 * The receipt again, for a sale or for a refund (`FR-7.5`, `D-145`).
 *
 * The answer is said out loud either way. A print is the one action whose
 * result the cashier cannot see from the screen — the paper comes out behind
 * them — so a silent success is indistinguishable from a dead printer, which is
 * the report this product refuses to give (`D-074`).
 */
const notice = useNoticeStore();

function said(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

async function reprint(order: OpenOrder): Promise<void> {
  const invoice = order.credit_note ?? order.sales_invoice;
  if (!invoice) return;

  try {
    await reprintReceipt(invoice);
    notice.info(t("print.receiptSent", { number: formatNumber(order.daily_number) }));
  } catch (cause) {
    notice.error(said(cause));
  }
}

/**
 * Paper again for the refund on screen (`D-171`).
 *
 * The sheet knows which credit note it is showing; the printing lives here with
 * every other reprint, so there is one path to a printer and one place that says
 * whether the paper went (`D-074`).
 */
async function reprintRefund(dailyNumber: number): Promise<void> {
  if (!refundOpen.value) return;

  try {
    await reprintReceipt(refundOpen.value);
    notice.info(t("print.receiptSent", { number: formatNumber(dailyNumber) }));
  } catch (cause) {
    notice.error(said(cause));
  }
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

/**
 * The item tapped before there was a bill to put it on.
 *
 * Which type the order should be is a real question — a table, a customer, a
 * price list hang off it — so the tap opens **جديد** rather than guessing one
 * (`D-056`). But the tap was still an order for a dish, and it used to be
 * thrown away: the cashier chose the type, landed on a menu, and had to find
 * the same item and tap it again. The second tap is the cashier doing the
 * screen's remembering for it.
 *
 * Held here and replayed once the order exists, whichever of the four creation
 * paths made it.
 */
const waitingPick = ref<{ item: CatalogItem; qty: number } | null>(null);

/** FR-2.2 — an item with modifier groups opens the popup first. */
function onPick(item: CatalogItem, qty: number): void {
  if (!maySell()) return;

  if (!orders.order) {
    waitingPick.value = { item, qty };
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

/**
 * The bill now exists **and the store is idle** — put the tap on the bill.
 *
 * Watched on the store rather than added at the end of each creation path:
 * there are four of them (straight, seated, named, counted) and they end in
 * three different functions. A step remembered in four places is a step
 * forgotten in one (`CLAUDE.md` §5.5), and the one it is forgotten in is the
 * one the cashier meets.
 *
 * **`busy` is half of the condition, not decoration.** The store runs one
 * action at a time and a second one taken while the first is in flight is
 * dropped and returns `null` — silently. `create` sets the order from *inside*
 * that flight, so flushing on the order alone put `addItem` into exactly that
 * window: an item with modifier groups worked, because its popup waits for the
 * cashier, and a plain item vanished. Waiting for idle also means the watcher
 * retries itself — the pick is only cleared once it has been replayed.
 *
 * It replays `onPick`, so an item with modifier groups still opens its popup
 * rather than landing plain.
 */
watch(
  () => [orders.order?.order_name ?? null, orders.busy] as const,
  ([name, busy]) => {
    const pick = waitingPick.value;
    if (!name || busy || !pick) return;

    waitingPick.value = null;
    onPick(pick.item, pick.qty);
  },
);

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
  if (!session.canSell) {
    // The detail dialog closes first: two stacked dialogs both answer Escape,
    // and one key would dismiss both (D-049).
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
  // BR-044 — taking a line off is cart work, and a bill that shrank after its
  // shift was counted is a shortfall nobody can trace (D-056).
  if (!maySell()) return;

  if (line.status === "pending") {
    void orders.removeLine(line.idx);
    return;
  }

  voidTarget.value = line;
}

async function confirmVoid(reason: string): Promise<void> {
  const line = voidTarget.value;
  if (!line) return;

  voidTarget.value = null;
  await orders.voidLine(line.idx, reason);
}

async function confirmCancel(reason: string): Promise<void> {
  const done = await orders.cancel(reason);
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
    // The one action that moves the order on; the rest are corrections to it.
    primary: true,
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

  // FR-9 — the only way to reverse a sale (D-063), so it is offered exactly
  // where a sale can be found: on a paid bill. `locked` is true for every
  // closed order, which is why this entry does not read it.
  if (orders.order?.status === "closed" && session.can("can_create_return")) {
    entries.push({
      key: "return",
      label: "ret.action",
      icon: "swap",
      disabled: orders.busy,
      destructive: true,
    });
  }

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

  // BR-063 — one party across more than one table. Offered only on a bill that
  // is already seated: a takeaway has nothing to join tables to, and the server
  // says so rather than the screen guessing.
  if (session.can("can_merge_tables") && orders.order?.table) {
    entries.push({
      key: "joinTables",
      label: "tables.join",
      icon: "floorPlan",
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

  // `D-248` — the guest mentions the code while ordering as often as at the
  // till, so it is reachable from both. One dialog answers it either way.
  entries.push({
    key: "coupon",
    label: "coupon.add",
    icon: "tag",
    disabled: locked.value,
  });

  // FR-2.12 — both move food between bills, so both live here rather than in
  // the row: a hand that lands without looking must not rearrange two bills.
  // Foodics keeps them in the same menu, next to Assign Table (`D-120`).
  if (session.can("can_split_bill")) {
    entries.push({
      key: "split",
      label: "split.action",
      icon: "swap",
      disabled: locked.value || !orders.order?.item_count,
    });
    entries.push({
      key: "join",
      label: "join.action",
      icon: "swap",
      disabled: locked.value,
    });
  }

  // D-106 — the bill's own history. Never disabled: reading is allowed with
  // no shift open, which is exactly when somebody is working out what
  // happened last night (`D-058` drew that line).
  entries.push({ key: "log", label: "log.action", icon: "document" });

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
  else if (action.key === "coupon") enteringCoupon.value = maySell();
  // BR-044 — both change the bill: one re-prices every line, the other ends it.
  else if (action.key === "convert") converting.value = maySell();
  else if (action.key === "cancel") cancelling.value = maySell();
  // FR-9 — a refund out of a counted drawer is a sale into one, backwards.
  else if (action.key === "return") returning.value = maySell();
  else if (action.key === "log") {
    logFor.value = null;
    showingLog.value = true;
  }
  else if (action.key === "split") splitting.value = maySell();
  else if (action.key === "join") joining.value = maySell();
  // BR-063 — one party across more than one table. `maySell` because it changes
  // the bill, and a counted drawer takes nothing more (`BR-044`).
  else if (action.key === "joinTables") joiningTables.value = maySell();
}

// --------------------------------------------------------------------------
// Splitting and joining bills (FR-2.12)
// --------------------------------------------------------------------------

const splitting = ref(false);
const joining = ref(false);

/**
 * Follow the food. A split leaves the cashier on the original bill with the new
 * one open beside it, which is what they asked for — they were dividing *this*
 * bill, and the guest paying the other half is the next thing they deal with.
 */
async function onSplit(): Promise<void> {
  splitting.value = false;
  await reload();
}

async function onJoined(): Promise<void> {
  joining.value = false;
  await reload();
}

// --------------------------------------------------------------------------
// One party across more than one table (BR-063)
// --------------------------------------------------------------------------

const joiningTables = ref(false);

/**
 * Say how many seats the party took, and go back to the floor.
 *
 * The floor is where the cashier can see what they just did — both tables drawn
 * taken — and seeing it is the only confirmation this action can give: nothing
 * on the bill itself changes.
 */
async function onTablesJoined(joined: string[]): Promise<void> {
  joiningTables.value = false;
  // One table is "طاولة واحدة", not "1 طاولات" (`D-238`): Arabic counts in
  // six forms, and the app has `tn` for exactly this.
  notice.info(tn("count.tablesJoined", joined.length));
  await reload();
  pane.value = "tables";
}

// --------------------------------------------------------------------------
// Returns (FR-9)
// --------------------------------------------------------------------------

const returning = ref(false);

/** Re-read the bill: the refund is on its record now, and on the shift's. */
async function onReturned(): Promise<void> {
  await reload();
  void shift.refresh();
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
  // BR-044 — asked here rather than on the payment screen, so the cashier is
  // not walked through a form they will be refused at the end of (D-058).
  if (!maySell()) return;

  // **Not `void`** (D-082). A rejected navigation resolves into nothing: the
  // button appears dead, the cashier taps it again, and there is not a word
  // anywhere to say why. Every path ends in something visible (`CLAUDE.md`
  // §5.5), and that includes the paths that are supposed to be impossible.
  router
    .push({ name: "payment", params: { orderName: orders.order.order_name } })
    .catch((cause) => {
      // The router answers a missing screen itself — it reloads, or says why
      // (`D-221`). A file URL on the order is not something a cashier can use.
      if (isMissingScreen(cause)) return;
      orders.error = cause instanceof Error ? cause.message : String(cause);
    });
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
  <!-- `minmax(0, 1fr)` columns, not the implicit `auto`: an auto track grows to
       its content's longest unbreakable line, so the action row made the whole
       screen 383px on a 360 phone and «المزيد» sat past the edge (`D-221`). -->
  <main class="grid h-full grid-cols-[minmax(0,1fr)] grid-rows-[minmax(0,1fr)] bg-background">
    <div class="grid min-h-0 grid-cols-[minmax(0,1fr)] grid-rows-[minmax(0,1fr)] p-[18px]">
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
      <!--
        **The menu starts, the bill ends** — and the screen mirrors itself with
        the language, without a single test on the language (`D-133`).

        Arabic puts the menu on the right and the bill on the left; English
        does the reverse. That is not two layouts: it is one order — you work
        through the menu and arrive at the total — laid along the inline axis.
        Grid already follows `dir`, which `i18n` sets on `<html>`, so the
        mirroring is free. A `locale === 'ar'` here would be the same thing
        written by hand, and it would drift the first time a third language or
        a per-user direction appears.

        The bill is a fixed band rather than a share of the width: the menu
        should take whatever a wider terminal offers, and the bill should not
        grow to 600px on one.
      -->
      <div
        class="grid min-h-0 gap-[18px] max-lg:grid-cols-[minmax(0,1fr)] max-lg:grid-rows-[minmax(0,1fr)_auto] lg:grid-cols-[minmax(0,1fr)_minmax(310px,380px)]"
      >
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
        <div class="flex min-h-0 flex-col gap-4">
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

            <!-- D-211 — a kitchen ticket whose paper never came, said on the
                 order instead of on a desk form nobody opens during service. -->
            <UnprintedTickets
              v-if="orders.order?.unprinted_tickets?.length"
              :tickets="orders.order?.unprinted_tickets ?? []"
              :may-reprint="session.can('can_reprint_receipt')"
              :busy="orders.busy"
              @reprint="orders.reprintTicket"
            />

            <!-- 09 §5, D-073 — a bill that lives on this device says so. It is
                 sellable and priced correctly, but nobody else can see it and a
                 wiped browser would lose it. -->
            <p
              v-if="orders.offline"
              role="status"
              class="flex items-center gap-2 rounded-rpos bg-status-cleaning/10 p-3 text-sm text-status-cleaning"
            >
              <AppIcon
                name="hourglass"
                :size="18"
              />
              {{ t("offline.bill") }}
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
            class="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)] rounded-rpos-lg border border-line bg-surface p-[18px]"
          >
            <ItemPicker
              :order-type="orderType"
              :disabled="locked"
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
            :view="floorView"
            :stale-at="floorStaleAt"
            :carried-count="floorCarriedCount"
            :include-carried="floorIncludeCarried"
            :may-reprint="session.can('can_reprint_receipt')"
            :older="floorOlder"
            :searching-older="floorSearchingOlder"
            @search-older="floorSearchOlder"
            @open="switchTo"
            @reprint="reprint"
            @floor-plan="pane = 'tables'"
            @update:view="floorView = $event"
            @update:include-carried="floorIncludeCarried = $event"
          />

          <FloorPane
            v-else-if="pane === 'tables'"
            class="min-h-0 flex-1"
            @seat="seat"
            @open="openOrder"
            @seat-booking="seatBooking"
          />

          <ReservationsPane
            v-else-if="pane === 'reservations'"
            class="min-h-0 flex-1"
            @seat="(booking) => seatBooking(booking.name, booking.table_number)"
          />

          <NewOrderPane
            v-else
            class="min-h-0 flex-1"
            :seating="pendingTable?.table_number ?? pendingReservation?.tableNumber ?? null"
            @open="startAnother"
          />

          <!-- Under the working column, so the bill beside it keeps the full
               height of the screen (06 Screen 3). -->
          <!-- `relative` anchors the menu sheet above the bar. -->
          <div
            ref="menuAnchor"
            class="relative"
          >
            <ShiftMenu
              :open="menuOpen"
              @select="onMenu"
            />

            <!-- D-220 — news about an action floats just above the bar and moves
                 nothing: it used to sit over the menu grid and push it down. -->
            <AppToast />

            <OrderBottomNav
              :entries="navEntries"
              :active="menuOpen ? 'menu' : pane"
              @select="onNavigate"
            />
          </div>
        </div>

        <!-- Drawn whether a bill is in hand or not (D-059): the bill is
             furniture, and a till that rearranges itself between customers is
             one the cashier has to re-read every time.

             **Below a landscape tablet it is a sheet, not a column** (`D-193`).
             Measured on a portrait iPad Mini (768 × 1024): stacked under the
             menu, an empty bill took 486px of the height and left the menu 387 —
             the tiles lost their pictures and a group's dishes showed a row and
             a half. `06` asked for a switch there from the start. So under `lg`
             the bill folds into a bar — how many items, and Pay with the total —
             and the same panel opens over the screen when the bar is tapped.

             One panel, two places: at `lg` both wrappers are `contents`, so the
             panel is the grid's second column exactly as it always was. -->
        <div
          ref="billAnchor"
          class="lg:contents"
        >
          <div
            class="flex items-center gap-3 rounded-rpos-lg border border-line bg-surface p-3 lg:hidden"
          >
            <button
              type="button"
              data-bill-toggle
              class="flex min-h-tap min-w-0 flex-1 items-center gap-2 rounded-rpos px-3 text-start font-medium transition duration-200 ease-rpos hover:bg-background"
              :aria-expanded="billOpen"
              @click="billOpen = !billOpen"
            >
              <AppIcon
                name="receipt"
                :size="20"
              />
              <span class="truncate">{{ t("order.bill") }}</span>
              <span class="rpos-numeric text-sm text-muted">{{ tn("count.items", orders.lines.length) }}</span>
            </button>
            <button
              type="button"
              data-bill-pay
              class="min-h-tap shrink-0 rounded-rpos bg-primary px-5 font-semibold text-primary-contrast transition duration-200 ease-rpos hover:brightness-110 disabled:opacity-50"
              :disabled="locked || orders.isEmpty"
              @click="goToPayment"
            >
              {{ t("order.payWithTotal", { total: formatNumber(orders.order?.total_amount ?? 0, 2) }) }}
            </button>
          </div>

          <!-- Inside the anchor, so it answers its own tap rather than through
               `useDismiss`, which counts anything in here as inside. -->
          <div
            v-if="billOpen"
            data-bill-backdrop
            class="fixed inset-0 z-30 bg-black/40 lg:hidden"
            aria-hidden="true"
            @click="billOpen = false"
          />

          <div
            data-bill-sheet
            class="max-lg:fixed max-lg:inset-x-0 max-lg:bottom-0 max-lg:z-40 max-lg:grid max-lg:h-[85dvh] max-lg:grid-rows-[auto_minmax(0,1fr)] max-lg:gap-2 max-lg:p-3 lg:contents"
            :class="billOpen ? '' : 'max-lg:hidden'"
          >
            <button
              type="button"
              class="min-h-tap justify-self-center rounded-full bg-surface px-5 text-sm font-medium shadow-card lg:hidden"
              @click="billOpen = false"
            >
              {{ t("order.hideBill") }}
            </button>
            <OrderPanel
              :order="orders.order"
              :lines="orders.lines"
              :busy="locked"
              :can-pay="!locked && !orders.isEmpty"
              @void="askVoid"
              @repeat="repeat"
              @inspect="inspect"
              @pay="goToPayment"
            />
          </div>
        </div>
      </div>
    </div>

    <RosterDialog
      :open="showingRoster"
      :pos-profile="session.profile?.name ?? null"
      @close="showingRoster = false"
    />

    <!-- The only way out of the app, so it asks first (D-055). -->
    <BaseDialog
      :open="signingOut"
      :title="t('home.logoutConfirm')"
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

    <!-- FR-9 — the only way to reverse a sale (D-063, D-064). -->
    <ActivityDialog
      v-model="showingLog"
      :order-name="logFor?.orderName ?? orders.order?.order_name ?? null"
      :number="logFor?.number ?? orders.order?.daily_number ?? null"
    />

    <SplitBillDialog
      :open="splitting"
      :order="orders.order"
      @close="splitting = false"
      @done="onSplit"
    />

    <JoinBillDialog
      :open="joining"
      :order="orders.order"
      @close="joining = false"
      @done="onJoined"
    />

    <!-- BR-063 — the other thing a restaurant calls merging: tables, not
         bills. Kept a separate dialog for that reason. -->
    <JoinTablesDialog
      :open="joiningTables"
      :order="orders.order"
      @close="joiningTables = false"
      @joined="onTablesJoined"
    />

    <ReturnDialog
      :open="returning"
      :order-name="orders.order?.order_name ?? null"
      @close="returning = false"
      @done="onReturned"
    />

    <!-- FR-2.1 step 4 — found by number, created from the same box (D-050). -->
    <CouponDialog
      :open="enteringCoupon"
      :order-name="orders.order?.order_name ?? null"
      :applied="orders.order?.coupon ?? null"
      @changed="void reload()"
      @close="enteringCoupon = false"
    />

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

    <TillReportDialog
      :open="viewingReport"
      @close="viewingReport = false"
    />

    <DrawerCashDialog
      :open="movingCash"
      @done="
        movingCash = false;
        void shift.refresh();
      "
      @close="movingCash = false"
    />

    <!-- `D-256` — the money lands in the open drawer, so the count is refreshed
         behind it exactly as a cash movement does. -->
    <GiftCardSellDialog
      :open="sellingGiftCard"
      @done="void shift.refresh()"
      @close="sellingGiftCard = false"
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
    <ReasonDialog
      :open="Boolean(voidTarget)"
      :title="t('order.voidReason')"
      :explain="voidTarget?.item_name ?? ''"
      :placeholder="t('order.voidPlaceholder')"
      :confirm="t('order.voidItem')"
      scope="void_reason"
      :busy="orders.busy"
      @confirm="confirmVoid"
      @close="voidTarget = null"
    />

    <ReasonDialog
      :open="cancelling"
      :title="t('order.cancelOrder')"
      :explain="t('order.cancelBody')"
      :placeholder="t('order.voidPlaceholder')"
      :confirm="t('order.confirmCancel')"
      scope="cancel_reason"
      :busy="orders.busy"
      @confirm="confirmCancel"
      @close="cancelling = false"
    />

    <!-- What a refund actually took back — read-only (`D-171`). -->
    <RefundDialog
      :open="Boolean(refundOpen)"
      :credit-note="refundOpen"
      @reprint="reprintRefund"
      @show-log="showLogFor"
      @close="refundOpen = null"
    />
  </main>
</template>

import { onUnmounted, ref } from "vue";

import { reductionsOn, type OrderDetail, type OrderLine } from "@/api/order";

/**
 * The screen the customer reads, and the channel that feeds it (`FR-13`).
 *
 * **Two windows of one browser on one machine**, which is what a customer
 * display is on a counter: the till on the cashier's monitor, this on the one
 * turned around. Lightspeed's desktop product is the same shape — a second
 * screen driven by software already running on that computer.
 *
 * ## Why not the WebSocket the spec named (`D-162`)
 *
 * `FR-13.3` said "via WebSocket channel per POS Profile". Three things against
 * it, and the third is the one that decides:
 *
 * 1. **There is no socket client in this app at all.** The server publishes
 *    (`publish_realtime` for tables and the kitchen) and nothing listens; every
 *    screen polls. A socket client is real infrastructure — the library, Frappe's
 *    realtime authentication — for a screen forty centimetres away.
 * 2. **It is a round trip to the same machine.** Slower and more fragile than
 *    handing the object across, for no gain.
 * 3. **The till sells offline** (`D-071`, `D-083`), and that is the whole point
 *    of this app on a bad line. A display fed by a socket goes blank exactly
 *    when the shop is under stress — the customer stops seeing their bill at
 *    the moment the cashier most needs them to.
 *
 * `BroadcastChannel` never leaves the browser, so it cannot be offline.
 *
 * **And the screen does not know the difference.** It consumes one state
 * object; a device-to-device transport can be added later behind the same
 * shape, which is what a paired tablet would need.
 */

/** Same-origin, and named so a second app on the machine cannot collide. */
const CHANNEL = "rpos-customer-display";

/** What the customer's screen is showing right now. */
export type DisplayMode = "idle" | "order" | "thanks";

/**
 * One line, as the customer reads it.
 *
 * **Deliberately not `OrderLine`.** Nothing here identifies a cashier, a
 * document or a terminal: the screen faces the room, and what is not sent
 * cannot be shown by a bug on the other side.
 */
export interface DisplayLine {
  name: string;
  qty: number;
  amount: number;
  /** Modifier options in the customer's words — research: guests follow these. */
  options: string[];
}

/**
 * What the restaurant looks like to the room, sent rather than looked up.
 *
 * The display window loads no session — it asks the server for nothing, by
 * design — so its own stores are empty and reading the branch there showed a
 * blank header. The till has all three; the till sends them (`D-202`).
 */
export interface Brand {
  /** The restaurant's name. */
  house: string;
  /** `RPOS Theme.brand_logo`, or `null` when the restaurant has not set one. */
  logo: string | null;
  /** The sentence a manager wrote for the waiting screen (`FR-13.1`). */
  message: string;
  /** Designed banners, turning (`D-203`). Empty when the restaurant has none. */
  banners: string[];
  /** How long each banner holds the screen, in seconds. */
  seconds: number;
}

export const NO_BRAND: Brand = { house: "", logo: null, message: "", banners: [], seconds: 8 };

export interface DisplayState extends Brand {
  mode: DisplayMode;
  lines: DisplayLine[];
  /** What the goods come to once the tax is taken out of them. */
  beforeTax: number;
  /**
   * The offer that was applied and what it took off — `null` when none was.
   *
   * Named to the guest rather than folded into the discount (`D-163`): an offer
   * they came in for is the thing they are looking for on this screen, and a
   * bare "discount" line does not tell them it was honoured.
   */
  promotion: { title: string; amount: number } | null;
  /** The guest's own points, spent on this bill (`D-189`). */
  loyalty: { points: number; amount: number } | null;
  /** What a person decided to take off, which is not the same thing. */
  discount: number;
  tax: number;
  total: number;
  /**
   * The number called out when the food is ready (`FR-2.10`).
   *
   * Its right home. It came off the orders list because that list mixes days
   * and the number restarts daily, so two rows could read the same (`D-159`).
   * Here there is one bill and no list, so it cannot be ambiguous — and the
   * research on customer displays says the same: after paying, what the guest
   * needs is their number.
   */
  number: number | null;
}

export const IDLE: DisplayState = {
  mode: "idle",
  ...NO_BRAND,
  lines: [],
  beforeTax: 0,
  promotion: null,
  loyalty: null,
  discount: 0,
  tax: 0,
  total: 0,
  number: null,
};

/** A window opening mid-order asks what is on screen rather than waiting. */
type Message = { type: "state"; state: DisplayState } | { type: "hello" };

function channel(): BroadcastChannel | null {
  // Absent in jsdom without a polyfill, and in an old webview. The till must
  // sell whether or not a second screen exists, so this is never fatal.
  return typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel(CHANNEL);
}

/** What the customer may see of a line — and nothing else. */
function toLine(line: OrderLine): DisplayLine {
  return {
    name: line.item_name,
    qty: line.qty,
    amount: line.amount,
    options: (line.modifiers ?? []).map((modifier) => modifier.option_ar || modifier.option),
  };
}

/**
 * The bill as the customer's screen should show it.
 *
 * Void lines are gone: a line taken off is not part of what is owed, and
 * leaving it visible is how a guest queries a total that is already right.
 */
export function toDisplayState(
  order: OrderDetail | null,
  lines: OrderLine[],
  brand: Brand = NO_BRAND,
): DisplayState {
  if (!order) return { ...IDLE, ...brand };

  return {
    mode: "order",
    ...brand,
    lines: lines.filter((line) => line.status !== "void").map(toLine),
    // **Before tax, not "subtotal"** — and the difference is the whole point.
    //
    // VAT here is inclusive (`D-091`), so `order.subtotal` already contains the
    // tax and printing it beside the tax and the total gave the guest
    // `60.00 + 7.83 = 60.00`. True, and it reads as a restaurant that cannot
    // add up. Derived from the total instead, the three figures add up on the
    // screen whichever way the branch charges tax.
    beforeTax: order.total_amount - order.tax_amount,
    // **The offer is named to the guest** (`D-163`). This is the one screen the
    // guest reads, and an offer they came in for is the thing they are checking
    // for — an unnamed "discount" line does not tell them it was applied. The
    // title is shop-facing text a manager wrote, and carries no cashier, no
    // document number and no terminal, so it does not widen what crosses the
    // channel (`D-162`).
    // The same subtraction the till and the payment screen make, made in the
    // same place so the three cannot disagree (§5.5).
    ...reductionsOn(order),
    tax: order.tax_amount,
    total: order.total_amount,
    number: order.daily_number || null,
  };
}

/** The till's end: push what the customer should be seeing. */
export function useCustomerDisplayPublisher() {
  const bus = channel();

  // A display opened after the bill was started would otherwise sit idle until
  // the next tap. It asks; this answers.
  let latest: DisplayState = IDLE;

  if (bus) {
    bus.onmessage = (event: MessageEvent<Message>) => {
      if (event.data?.type === "hello") bus.postMessage({ type: "state", state: latest });
    };
  }

  function publish(state: DisplayState): void {
    latest = state;
    bus?.postMessage({ type: "state", state });
  }

  onUnmounted(() => bus?.close());

  return { publish };
}

/**
 * What arrived, filled out to a whole state.
 *
 * **The two windows are not updated at the same instant.** A till still running
 * yesterday's code sends yesterday's shape, and the screen reading it reached
 * for a field that was not there — `state.banners.length` threw, the render
 * failed, and **the guest's bill disappeared with it** (found by the user, on a
 * till not yet refreshed after `D-203`).
 *
 * So the channel's edge is where the shape is settled: anything missing takes
 * its idle value, and the screen downstream can trust every field.
 */
export function received(state: Partial<DisplayState> | null | undefined): DisplayState {
  return { ...IDLE, ...(state ?? {}) };
}

/** The customer screen's end: whatever the till last said. */
export function useCustomerDisplayReceiver() {
  const state = ref<DisplayState>(IDLE);
  /**
   * Whether the till has ever answered.
   *
   * **A screen that has heard nothing looks exactly like a screen waiting for
   * the next guest** — a quiet welcome and a clock, which is what the user was
   * looking at while the till beside it held an open bill. The channel does not
   * cross browsers or origins (`localhost` is not `rpos.localhost`), so this is
   * the one failure this window can have, and it was invisible.
   */
  const linked = ref(false);
  const bus = channel();

  if (bus) {
    bus.onmessage = (event: MessageEvent<Message>) => {
      if (event.data?.type !== "state") return;

      state.value = received(event.data.state);
      linked.value = true;
    };
    bus.postMessage({ type: "hello" });
  }

  onUnmounted(() => bus?.close());

  return { state, linked };
}

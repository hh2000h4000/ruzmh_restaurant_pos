/**
 * Order endpoints (07 §3).
 *
 * Every write goes through `mutate`, which attaches the `queue_id` that makes a
 * retry safe (09 §8). Nothing here computes money — the server returns the
 * totals and the store stores what it is given (CLAUDE.md §5.1).
 */
import { mutate, query } from "./client";

import { pick, t } from "@/i18n";
import { mutateOrQueue, type Queued } from "@/offline/queue";

/**
 * What a promotion took off this bill, and which one (`D-163`).
 *
 * Part of `discount_amount` rather than a second reduction — the server folds
 * both into one figure so the tax is worked out once — and named separately
 * because a promotion is not a discount (`BR-032`): one is a rule the shop
 * configured, the other is a person deciding. A cashier who cannot tell the two
 * apart cannot answer the guest who asks why the total moved, and a manager
 * being asked to approve a discount must be shown the discount alone.
 *
 * One shape carried by every payload that reports a total, because the till, the
 * payment screen and the guest's screen ask the same question (§5.5).
 *
 * The titles are empty when no promotion applied, and on a bill built offline —
 * where none is.
 */
export interface PromotionOnBill {
  promotion_amount: number;
  /** The offer the bill is filed under — the highest-ranked of them. */
  promotion_title: string;
  promotion_title_ar: string;
  /**
   * Every offer that landed, and what each one took (`D-182`).
   *
   * A bill may carry several now, on different lines (`BR-034`). Optional
   * because a bill built offline ran no engine, and an older server does not
   * send it — in both cases the single title above still stands.
   */
  promotions?: { name: string; title: string; title_ar: string; amount: number }[];
  /**
   * The code that unlocked an offer, when one did (`D-248`).
   *
   * Carried on the bill rather than held by whichever screen typed it: the
   * guest may present it at the order screen and ask about it at the payment
   * screen, and both have to be able to name it and take it back off.
   */
  coupon?: { name: string; code: string; campaign: string } | null;
}

/**
 * What one customer's points can do on this bill (`FR-10.5`, `D-189`).
 *
 * Worked out on the server on the bill as it stands — after the discount and
 * the offer — so `max_points` is exactly what the payment will accept.
 */
export interface LoyaltyOffer {
  balance: number;
  /** What the whole balance is worth, in money. */
  worth: number;
  point_value: number;
  /** Nothing can be spent below this balance. */
  min_points: number;
  /** The most this bill can take now; zero when nothing can be spent. */
  max_points: number;
  /** What `max_points` would take off — sent, never multiplied here (§5.1). */
  max_amount: number;
}

/**
 * Points on a bill (`D-189`). Optional throughout: a bill built offline spends
 * none, and an older server sends none.
 */
export interface LoyaltyOnBill {
  /** Points spent on this bill. */
  loyalty_points?: number;
  /** What they took off, inside `discount_amount`. */
  loyalty_amount?: number;
  /**
   * The customer's balance and limits — `null` when the bill is outside the
   * scheme: no customer, the terminal's own, an order type with loyalty off, or
   * no program. Only the payment screen is sent this.
   */
  loyalty?: LoyaltyOffer | null;
}

/**
 * The bill before VAT, for every screen that lists the tax under it.
 *
 * VAT here is inclusive (`D-091`), so `subtotal` already holds the tax, and
 * printing it over the tax and the total read `25.00 + 3.26 = 25.00` — true,
 * and a till that cannot add up. Derived from the total instead, the column
 * sums whichever way the branch charges tax. The guest's screen did this first
 * (`D-162`); the till's own panel follows (`D-371`), from here, so the two
 * cannot disagree (§5.5).
 */
export function beforeTaxOn(bill: { total_amount: number; tax_amount: number } | null): number {
  if (!bill) return 0;
  return Math.round((bill.total_amount - bill.tax_amount) * 100) / 100;
}

/**
 * The two reductions, told apart — for every screen that shows a total.
 *
 * The server folds both into `discount_amount` so the tax is worked out once,
 * which is right, and leaves one figure standing for two different things. Every
 * screen that draws them has to undo that fold the same way, so it is undone
 * here once: the till, the payment screen and the guest's screen were three
 * copies of one subtraction, which is how two of them end up disagreeing (§5.5).
 *
 * An amount with no name draws no offer line. That is a bill built offline,
 * where the engine did not run (`D-163`), and a nameless line the guest cannot
 * read is worse than none.
 */
export function reductionsOn(
  bill: (PromotionOnBill & LoyaltyOnBill & { discount_amount: number }) | null,
): {
  promotion: { title: string; amount: number } | null;
  loyalty: { points: number; amount: number } | null;
  discount: number;
} {
  if (!bill) return { promotion: null, loyalty: null, discount: 0 };

  const amount = bill.promotion_amount ?? 0;

  // **Named by all of them when there are several** (`D-182`). A line reading
  // "خصم الشوايات ‎-13.00" on a bill where 8.00 of that came off the drinks is
  // the same unanswerable report as no name at all: the guest points at a dish
  // the named offer never touched. Joined in the catalogue's own separator, so
  // the list reads as a list in either language.
  const carried = bill.promotions ?? [];
  const title =
    carried.length > 1
      ? carried.map((row) => pick(row.title_ar, row.title)).join(t("common.listSeparator"))
      : pick(bill.promotion_title_ar, bill.promotion_title);

  const named = amount > 0 && Boolean(title);

  // **The points are a line of their own** (`D-189`). The guest spent their own
  // balance; nobody at the till discounted anything, and a manager asked to
  // approve a discount must not be shown the points as one.
  const spent = bill.loyalty_amount ?? 0;

  return {
    promotion: named ? { title, amount } : null,
    loyalty: spent > 0 ? { points: bill.loyalty_points ?? 0, amount: spent } : null,
    // Only what was actually shown as an offer is taken out of the discount, or
    // an unnamed promotion would vanish from the bill altogether. Rounded to the
    // halala, because three floats subtracted leave 1e-15 behind and a discount
    // line reading −0.00 is a line the guest asks about.
    discount: Math.round((bill.discount_amount - (named ? amount : 0) - spent) * 100) / 100,
  };
}

/**
 * Which document a row on the orders list actually opens (`D-171`).
 *
 * **A refund row carries the sale's `name`**, so its card can wear the sale's
 * table, type and customer — the refund reverses that bill and belongs beside
 * it. The cost is that the obvious reading of a tap opens the sale: a cashier
 * who returned two dishes off a bill of four got all four, at positive prices,
 * from a row labelled *refund* showing a negative figure.
 *
 * Decided here rather than inline in the screen because that is the only way to
 * hold it: the defect was invisible to every backend test, and breaking the
 * routing left the whole suite green until this existed.
 */
export type OpenTarget =
  | { kind: "refund"; creditNote: string }
  | { kind: "order"; orderName: string }
  | { kind: "queued" };

export function whatOpens(order: OpenOrder): OpenTarget {
  // D-075 — a queued sale is one entry in a queue until the server has it.
  // Listing it answers "where did my bill go"; opening it promises what nothing
  // can keep.
  if (order.status === "queued") return { kind: "queued" };

  if (order.is_return && order.credit_note) {
    return { kind: "refund", creditNote: order.credit_note };
  }

  return { kind: "order", orderName: order.name };
}

export interface OrderSummary extends PromotionOnBill {
  order_name: string;
  status: string;
  subtotal: number;
  discount_amount: number;
  tax_amount: number;
  total_amount: number;
  item_count: number;
}

export interface OrderLine {
  idx: number;
  item: string;
  item_name: string;
  qty: number;
  rate: number;
  amount: number;
  /**
   * This line's share of the promotion, `0` when the offer did not reach it.
   *
   * **The bill's total cannot say which dish an offer came off** (`D-166`), and
   * that is the question the guest asks while pointing at one. The shares add up
   * to the figure in the totals block exactly — the server allocates them.
   */
  promotion_amount: number;
  status: "pending" | "sent" | "void" | "served";
  notes: string | null;
  /**
   * `amount` is the option's own price, not a signed delta — the server stores
   * it that way and `price_effect` says which direction it pulls (D-076).
   */
  modifiers: {
    group: string;
    option: string;
    option_ar: string;
    amount: number;
    price_effect?: "none" | "add" | "subtract";
    /** `combo` — one of a combo's items, listed under it (D-285). */
    item_effect?: string;
    /** A combo item's own add-ons, chosen on it (D-289). */
    modifiers?: { option: string; option_ar: string }[];
  }[];
  production_center: string | null;
}

export interface OrderDetail extends OrderSummary {
  /** The short number the customer is told; `order_name` is the record id. */
  daily_number: number;
  /** A name to call out — not a Customer (FR-2.11). */
  call_name: string | null;
  order_type: string;
  table: string | null;
  /** What the table is called on the floor, not its record id. */
  table_number: string | null;
  /**
   * Every seat this bill holds, its own first (`BR-063`).
   *
   * One party can be spread across two tables, and the bill is what remembers
   * — occupancy is read from the bills and nothing else tracks it.
   */
  tables: string[];
  /** The hall it is seated in; a party is not spread across two of them. */
  section: string | null;
  customer: string | null;
  /** The bill names the customer, and a Customer's id is not their name. */
  customer_name: string | null;
  customer_mobile: string | null;
  delivery_address: string | null;
  /** The address in words — a driver cannot read `ADDR-00012`. */
  delivery_address_line: string | null;
  cover_count: number;
  /** Printed on every station's ticket, unlike a line's own note (FR-2.9). */
  notes: string | null;
  opened_at: string;
  items: OrderLine[];
  /** Tickets still on their way to a printer — the screen checks back while this is above zero. */
  tickets_printing?: number;
}

export type OpenOrderStatus =
  | "draft"
  | "active"
  | "in_kitchen"
  | "pending_payment"
  | "closed"
  | "cancelled"
  /**
   * Sold on this device, not yet on the server (D-075).
   *
   * The only status that is not a `Restaurant Order.status` — nothing on the
   * server carries it, because nothing on the server knows about the bill yet.
   */
  | "queued";

/** One card on the home screen (06 Screen 1). */
export interface OpenOrder {
  name: string;
  daily_number: number;
  call_name: string | null;
  order_type: string;
  order_type_title: string;
  order_type_title_ar: string;
  icon: string | null;
  color: string | null;
  status: OpenOrderStatus;
  table: string | null;
  table_number: string | null;
  cover_count: number;
  customer: string | null;
  cashier: string | null;
  cashier_name: string | null;
  total_amount: number;
  /** FR-9 — what went back to the customer, `0` when nothing did (D-070). */
  returned_amount: number;
  opened_at: string;
  /**
   * When the bill ended — payment or cancellation — and `null` while it is open.
   *
   * A history row is dated by **this**, not by when it was opened (`D-146`): a
   * bill opened at eleven and paid at one belongs to the day that took the
   * money. On a refund row it is when the refund happened.
   */
  closed_at: string | null;
  item_count: number;
  /**
   * This row **is** a refund, not a sale that had one (`D-143`).
   *
   * Only the `returned` tab produces these: one row per credit note, with its
   * own number, its own time, and `total_amount` negative because that is the
   * direction the money went. The rest of the card is the sale's — the type,
   * the table, the customer are all still true of it.
   */
  is_return?: 0 | 1;
  /** The credit note behind a refund row, for reprinting it. */
  credit_note?: string;
  /** The sale's invoice, once there is one — what a closed row reprints. */
  sales_invoice?: string | null;
  /** The bill this refund reverses, so the card can name it. */
  returns_daily_number?: number;
  /** Who it was billed to — a company knows its own name (`D-152`). */
  customer_name?: string | null;
  /**
   * Open, but from a business day that has already ended (`D-164`).
   *
   * It decides two things on the screen: whether the row is drawn as carried in
   * the mixed tab, and whether its **daily number** is shown at all — that
   * number restarts at one every day, so on today's floor it names the bill and
   * on a three-day-old one two rows can read the same (`D-159`).
   */
  is_carried: 0 | 1;
}

export interface ModifierChoice {
  group: string;
  option: string;
}

/**
 * Which orders the pane is asking for (06 Screen 3).
 *
 * `returned` is the day's refunds, one row per credit note (`D-143`). It used to
 * list the *bills* money had gone back out of, on the reasoning that a credit
 * note is not an order — sound, and answering the wrong question: these history
 * tabs are the day's transactions, and a refund is one of them.
 *
 * **Every one of these is a status, and a bill's age is not one** (`D-168`).
 * `open` holds today's floor; bills carried from a day that has closed are asked
 * for *inside* it — a carried bill is an open bill.
 */
export type OrderView = "open" | "closed" | "returned" | "all";

/** Branch-wide, not terminal-wide — see the docstring on the endpoint. */
export function listOrders(
  posProfile: string,
  view: OrderView = "open",
  includeCarried = false,
): Promise<OpenOrder[]> {
  return query<OpenOrder[]>("order.list_orders", {
    pos_profile: posProfile,
    view,
    include_carried: includeCarried ? 1 : 0,
  });
}

/**
 * How many bills are carried, for the switch to say so without being turned on.
 *
 * A count rather than a list: a switch that has to be turned on to learn whether
 * it holds three bills or three hundred hides the number as surely as the old
 * mixed list did (`D-164`).
 */
export function countCarriedOrders(posProfile: string): Promise<{ carried: number }> {
  return query<{ carried: number }>("order.count_carried_orders", { pos_profile: posProfile });
}

/**
 * Find a bill the tabs no longer hold (`D-152`).
 *
 * Asked for by hand, never on a keystroke: the tabs are today, and this reaches
 * back over months. The server bounds both the window and the number of rows,
 * so what comes back is always small enough to draw.
 */
export function searchOrders(posProfile: string, text: string): Promise<OpenOrder[]> {
  return query<OpenOrder[]>("order.search_orders", { pos_profile: posProfile, query: text });
}

/**
 * Not deferrable. The screen needs the order name the server assigns before it
 * can do anything else, and inventing one locally is the offline-order slice,
 * not this one.
 */
export function createOrder(payload: {
  order_type: string;
  pos_profile: string;
  table?: string | null;
  customer?: string | null;
  delivery_address?: string | null;
  cover_count?: number | null;
  order_type_data?: Record<string, unknown>;
}): Promise<OrderSummary> {
  return mutate<OrderSummary>("order.create_order", payload);
}

export function getOrder(orderName: string): Promise<OrderDetail> {
  return query<OrderDetail>("order.get_order", { order_name: orderName });
}

/**
 * Not deferrable yet. Queuing this would take the line off the screen while
 * keeping it in the queue, and the cashier would tap again — one order, two of
 * everything. It becomes deferrable when the device keeps its own copy of the
 * order (`09` §3 `active_orders`).
 */
export function addItem(payload: {
  order_name: string;
  item: string;
  qty?: number;
  modifiers?: ModifierChoice[];
  notes?: string | null;
  /** The typed price of an open-price dish (`D-378`); the server prices the rest. */
  rate?: number;
}): Promise<OrderSummary & { row_idx: number }> {
  return mutate("order.add_item", payload);
}

/**
 * Change how many of a line, before the kitchen has it.
 *
 * Not deferrable, for the same reason as `addItem`: the number has to change
 * on screen and on the server together.
 */
export function setItemQty(payload: {
  order_name: string;
  item_idx: number;
  qty: number;
}): Promise<OrderSummary & { item_idx: number; qty: number; amount: number }> {
  return mutate("order.set_item_qty", payload);
}

/** Not deferrable yet, for the same reason as `addItem`. */
export function voidItem(payload: {
  order_name: string;
  item_idx: number;
  reason: string;
  manager_override_token?: string | null;
}): Promise<OrderSummary> {
  return mutate("order.void_item", payload);
}

/**
 * Deferrable. The cashier is walking away from this order either way, and the
 * screen can say "cancelled, waiting to sync" honestly. The order stays open on
 * the server until the queue drains, which is the truth.
 */
export function cancelOrder(payload: {
  order_name: string;
  reason: string;
  manager_override_token?: string | null;
}): Promise<OrderSummary | Queued> {
  return mutateOrQueue("order.cancel_order", payload);
}

/** What the bill would become under another type — read-only (D-038). */
export interface OrderTypeChangePreview {
  order_type: string;
  price_list: string | null;
  total_before: number;
  total_after: number;
  changed_lines: { item: string; item_name: string; was: number; now: number }[];
  requires_table: 0 | 1 | boolean;
  requires_cover_count: 0 | 1 | boolean;
}

export function previewOrderTypeChange(payload: {
  order_name: string;
  order_type: string;
}): Promise<OrderTypeChangePreview> {
  return query<OrderTypeChangePreview>("order.preview_order_type_change", payload);
}

/**
 * Turn an open order into another type (D-038).
 *
 * Not deferrable. The new total is the server's answer — the price list may
 * differ — and a screen that showed a converted bill before the server agreed
 * would be reading the customer a number nobody has computed.
 */
export function changeOrderType(payload: {
  order_name: string;
  order_type: string;
  table?: string | null;
  cover_count?: number | null;
  manager_override_token?: string | null;
}): Promise<OrderSummary & { order_type: string; changed: boolean }> {
  return mutate("order.change_order_type", payload);
}

/**
 * Seat an open order at a table, or move it to another one (BR-061).
 *
 * Not deferrable. A table is shared state — two tills seating different orders
 * on table four must not both be told yes — so the server decides.
 */
export function setOrderTable(payload: {
  order_name: string;
  table: string;
  cover_count?: number | null;
  manager_override_token?: string | null;
}): Promise<OrderSummary & { table: string; changed: boolean; moved_from?: string | null }> {
  return mutate("order.set_order_table", payload);
}

/**
 * Set the note printed on every station's ticket (FR-2.9).
 *
 * Not deferrable. A note the kitchen has not been told is a note that did not
 * happen, and this one exists for allergies.
 */
export function setOrderNotes(payload: {
  order_name: string;
  notes: string | null;
}): Promise<OrderSummary & { notes: string | null; changed: boolean }> {
  return mutate("order.set_order_notes", payload);
}

/**
 * Change one line's note (FR-2.9).
 *
 * Not deferrable: when the line is already with the kitchen the server also
 * corrects the station's ticket, and a note the kitchen was not told is a note
 * that did not happen.
 */
export function setItemNotes(payload: {
  order_name: string;
  item_idx: number;
  notes: string | null;
}): Promise<OrderSummary & { item_idx: number; notes: string | null; changed: boolean }> {
  return mutate("order.set_item_notes", payload);
}

/**
 * Take a line off before the kitchen has seen it (FR-2.5).
 *
 * Distinct from `voidItem` on purpose: no reason, no permission, no trail.
 * Until the ticket prints, this is composing an order rather than withdrawing
 * food, and a reason box on every mis-tap costs seconds at every till.
 */
export function removeItem(payload: {
  order_name: string;
  item_idx: number;
}): Promise<OrderSummary & { removed: number }> {
  return mutate("order.remove_item", payload);
}

/**
 * Attach a customer to an open order, or take one off (FR-2.1 step 4).
 *
 * Not deferrable. Which customer a bill belongs to decides the price list, the
 * VAT number on the invoice and where a delivery goes — a screen that showed a
 * customer the server never accepted would be reading a bill nobody has filed.
 */
export function setOrderCustomer(payload: {
  order_name: string;
  customer?: string | null;
  delivery_address?: string | null;
}): Promise<OrderSummary & { customer: string | null; delivery_address: string | null }> {
  return mutate("order.set_order_customer", payload);
}

/** Name the order for calling out — not a Customer (FR-2.11). */
export function setCallName(payload: {
  order_name: string;
  call_name: string | null;
}): Promise<OrderSummary & { call_name: string | null; changed: boolean }> {
  return mutate("order.set_call_name", payload);
}

/** One line a cashier has chosen to move, whole or in part (`BR-067`). */
export interface MovedLine {
  idx: number;
  qty?: number;
}

export interface SplitPreview {
  source: { subtotal: number; tax_amount: number; total_amount: number };
  target: { subtotal: number; tax_amount: number; total_amount: number };
}

/**
 * What each side of a split would come to.
 *
 * Asked of the server because a total is money (`CLAUDE.md` §5.1), the same
 * reason `previewTotals` exists for a discount: the figure the cashier reads to
 * a customer has to be the figure the invoice will carry.
 */
export function previewSplit(orderName: string, rows: MovedLine[]): Promise<SplitPreview> {
  return query<SplitPreview>("order.preview_split", { order_name: orderName, rows });
}

/** Move the chosen lines onto a bill of their own (`FR-2.12`). */
export function splitBill(payload: {
  order_name: string;
  rows: MovedLine[];
  queue_id?: string;
}): Promise<OrderSummary & { target: string }> {
  return mutate("order.split_bill", payload);
}

/**
 * Join free tables to this bill for one party across several (`BR-063`).
 *
 * **Not the same act as `mergeBills`**, though a restaurant calls both
 * "merging": this leaves every bill alone and gives one bill a second seat;
 * that empties one bill into another. A table that already carries a bill is
 * refused here, and the refusal says to merge the bills instead.
 */
export function mergeTables(payload: {
  order_name: string;
  tables: string[];
  manager_override_token?: string | null;
  queue_id?: string;
}): Promise<OrderSummary & { table: string; tables: string[]; joined: string[] }> {
  return mutate("order.merge_tables", payload);
}

/** Empty one bill into another and close it (`FR-2.12`). */
export function mergeBills(payload: {
  order_name: string;
  into: string;
  queue_id?: string;
}): Promise<OrderSummary & { merged: string }> {
  return mutate("order.merge_bills", payload);
}

/**
 * Order endpoints (07 §3).
 *
 * Every write goes through `mutate`, which attaches the `queue_id` that makes a
 * retry safe (09 §8). Nothing here computes money — the server returns the
 * totals and the store stores what it is given (CLAUDE.md §5.1).
 */
import { mutate, query } from "./client";

import { mutateOrQueue, type Queued } from "@/offline/queue";

export interface OrderSummary {
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
  status: "pending" | "sent" | "void" | "served";
  notes: string | null;
  modifiers: { group: string; option: string; option_ar: string; amount: number }[];
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
  customer: string | null;
  /** The bill names the customer, and a Customer's id is not their name. */
  customer_name: string | null;
  cover_count: number;
  /** Printed on every station's ticket, unlike a line's own note (FR-2.9). */
  notes: string | null;
  opened_at: string;
  items: OrderLine[];
}

export type OpenOrderStatus =
  | "draft"
  | "active"
  | "in_kitchen"
  | "pending_payment"
  | "closed"
  | "cancelled";

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
  opened_at: string;
  order_minutes: number;
  item_count: number;
}

export interface ModifierChoice {
  group: string;
  option: string;
}

/** Which orders the pane is asking for (06 Screen 3). */
export type OrderView = "open" | "draft" | "closed" | "all";

/** Branch-wide, not terminal-wide — see the docstring on the endpoint. */
export function listOrders(posProfile: string, view: OrderView = "open"): Promise<OpenOrder[]> {
  return query<OpenOrder[]>("order.list_orders", { pos_profile: posProfile, view });
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

/** Name the order for calling out — not a Customer (FR-2.11). */
export function setCallName(payload: {
  order_name: string;
  call_name: string | null;
}): Promise<OrderSummary & { call_name: string | null; changed: boolean }> {
  return mutate("order.set_call_name", payload);
}

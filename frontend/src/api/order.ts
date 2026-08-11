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
  order_type: string;
  table: string | null;
  customer: string | null;
  cover_count: number;
  opened_at: string;
  items: OrderLine[];
}

export type OpenOrderStatus = "draft" | "active" | "in_kitchen" | "pending_payment";

/** One card on the home screen (06 Screen 1). */
export interface OpenOrder {
  name: string;
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
  total_amount: number;
  opened_at: string;
  order_minutes: number;
  item_count: number;
}

export interface ModifierChoice {
  group: string;
  option: string;
}

/** Branch-wide, not terminal-wide — see the docstring on the endpoint. */
export function getOpenOrders(posProfile: string): Promise<OpenOrder[]> {
  return query<OpenOrder[]>("order.get_open_orders", { pos_profile: posProfile });
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

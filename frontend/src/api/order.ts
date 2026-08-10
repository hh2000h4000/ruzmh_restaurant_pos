/**
 * Order endpoints (07 §3).
 *
 * Every write goes through `mutate`, which attaches the `queue_id` that makes a
 * retry safe (09 §8). Nothing here computes money — the server returns the
 * totals and the store stores what it is given (CLAUDE.md §5.1).
 */
import { mutate, query } from "./client";

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

export interface ModifierChoice {
  group: string;
  option: string;
}

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

export function addItem(payload: {
  order_name: string;
  item: string;
  qty?: number;
  modifiers?: ModifierChoice[];
  notes?: string | null;
}): Promise<OrderSummary & { row_idx: number }> {
  return mutate("order.add_item", payload);
}

export function voidItem(payload: {
  order_name: string;
  item_idx: number;
  reason: string;
  manager_override_token?: string | null;
}): Promise<OrderSummary> {
  return mutate("order.void_item", payload);
}

export function cancelOrder(payload: {
  order_name: string;
  reason: string;
  manager_override_token?: string | null;
}): Promise<OrderSummary> {
  return mutate("order.cancel_order", payload);
}

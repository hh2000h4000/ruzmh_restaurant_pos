/**
 * A bill the device owns, because there is no server to own it (09 §5, D-073).
 *
 * **It wears the same shape as a server order.** Every screen already renders an
 * `OrderDetail`; giving them a second type to branch on would put "are we
 * offline" into the bill panel, the line row and the payment screen — three
 * places to forget it. This builds an `OrderDetail` from local state instead,
 * and the screens never learn the difference.
 *
 * Two things it does not pretend:
 *
 * - **`order_name` is the queue id**, prefixed so it cannot be mistaken for
 *   `RO-2026-08-01047`. It is what the bill will be submitted under (`D-072`),
 *   so the local record and the eventual replay are the same identity rather
 *   than two that have to be reconciled.
 * - **`daily_number` is 0** until the server assigns one. A number invented here
 *   would be read out to a customer and then not exist.
 *
 * Every total comes from `money/totals.ts` — the port held to the same contract
 * as the backend (`D-071`). Nothing on this path invents arithmetic.
 */

import type { ModifierChoice, OrderDetail, OrderLine } from "@/api/order";
import { computeTotals, type DiscountType, type Pricing } from "@/money/totals";

import { database, type LocalOrder } from "./db";

/** What the till knows about one line before any server has seen it. */
export interface LocalLine {
  item: string;
  item_name: string;
  qty: number;
  rate: number;
  modifiers: OrderLine["modifiers"];
  notes: string | null;
}

export interface LocalOrderState {
  local_id: string;
  order_type: string;
  opened_at: string;
  lines: LocalLine[];
  discount_type: DiscountType;
  discount_value: number;
  call_name: string | null;
  table: string | null;
  customer: string | null;
  cover_count: number;
  notes: string | null;
}

/** `RO-` is the server's; this can never be confused with one. */
const PREFIX = "OFF-";

export function isLocalOrder(orderName: string | null | undefined): boolean {
  return Boolean(orderName?.startsWith(PREFIX));
}

export function newLocalOrder(orderType: string, queueId: string): LocalOrderState {
  return {
    local_id: PREFIX + queueId,
    order_type: orderType,
    opened_at: new Date().toISOString(),
    lines: [],
    discount_type: null,
    discount_value: 0,
    call_name: null,
    table: null,
    customer: null,
    cover_count: 0,
    notes: null,
  };
}

/** The queue id this bill will be submitted under — the local id without the tag. */
export function queueIdOf(state: LocalOrderState): string {
  return state.local_id.slice(PREFIX.length);
}

/**
 * The shape every screen already knows how to draw.
 *
 * Lines are `pending` because nothing has reached a kitchen: no station has the
 * ticket while the line is down, and marking them `sent` would let a cashier
 * void something that was never cooked.
 */
export function toOrderDetail(state: LocalOrderState, pricing: Pricing): OrderDetail {
  const amounts = state.lines.map(lineAmount);
  const totals = computeTotals(amounts, state.discount_type, state.discount_value, pricing);

  const items: OrderLine[] = state.lines.map((line, index) => ({
    idx: index + 1,
    item: line.item,
    item_name: line.item_name,
    qty: line.qty,
    rate: line.rate,
    amount: lineAmount(line),
    status: "pending",
    notes: line.notes,
    modifiers: line.modifiers,
    production_center: null,
  }));

  return {
    order_name: state.local_id,
    status: "draft",
    subtotal: totals.subtotal,
    discount_amount: totals.discount_amount,
    tax_amount: totals.tax_amount,
    total_amount: totals.total_amount,
    item_count: items.length,
    daily_number: 0,
    call_name: state.call_name,
    order_type: state.order_type,
    table: state.table,
    table_number: null,
    customer: state.customer,
    customer_name: null,
    customer_mobile: null,
    delivery_address: null,
    delivery_address_line: null,
    cover_count: state.cover_count,
    notes: state.notes,
    opened_at: state.opened_at,
    items,
  };
}

/**
 * One line, modifiers included — mirrors `utils/order._resolve_modifiers` and
 * `utils/totals.line_amount`.
 *
 * `replace` adds like `add` does. That looks wrong and is what the server does
 * (`utils/order.py`), so the port follows it rather than improving on it: a
 * device that computed the "better" answer would disagree with the invoice.
 */
function lineAmount(line: LocalLine): number {
  const delta = line.modifiers.reduce((sum, modifier) => {
    const amount = modifier.amount || 0;
    if (modifier.price_effect === "subtract") return sum - amount;
    if (modifier.price_effect === "none") return sum;
    return sum + amount;
  }, 0);

  return (line.rate + delta) * line.qty;
}

/** What `api/offline.submit_order` expects (D-072). */
export function toSubmission(
  state: LocalOrderState,
  pricing: Pricing,
  payments: { method: string; amount: number; tendered?: number }[],
): Record<string, unknown> {
  const detail = toOrderDetail(state, pricing);

  return {
    order_type: state.order_type,
    opened_at: state.opened_at,
    table: state.table,
    customer: state.customer,
    cover_count: state.cover_count || null,
    call_name: state.call_name,
    notes: state.notes,
    lines: state.lines.map((line) => ({
      item: line.item,
      qty: line.qty,
      modifiers: line.modifiers.map(
        (modifier): ModifierChoice => ({ group: modifier.group, option: modifier.option }),
      ),
      notes: line.notes,
    })),
    discount_type: state.discount_type,
    discount_value: state.discount_value,
    payments,
    // What the customer was told. The server checks it and refuses rather than
    // posting one of two figures (D-072).
    totals: {
      subtotal: detail.subtotal,
      discount_amount: detail.discount_amount,
      tax_amount: detail.tax_amount,
      total_amount: detail.total_amount,
    },
    // Carried so a refused sync can say *why* the two disagreed rather than only
    // that they did.
    pricing,
  };
}

// ---------------------------------------------------------------------------
// Storage — `active_orders`, which the schema has held since v1
// ---------------------------------------------------------------------------

export async function save(state: LocalOrderState): Promise<void> {
  const db = await database();
  if (!db) return;

  const record: LocalOrder = {
    local_id: state.local_id,
    server_id: null,
    status: "draft",
    data: state,
    last_modified: new Date().toISOString(),
    is_synced: false,
  };

  try {
    await db.put("active_orders", record);
  } catch (cause) {
    // The bill is still on screen and still sellable; what is lost is surviving
    // a reload. Saying so beats a silent failure the cashier finds later.
    console.error("[rpos] could not store the offline order:", cause);
  }
}

export async function load(localId: string): Promise<LocalOrderState | null> {
  const db = await database();
  if (!db) return null;

  try {
    const record = await db.get("active_orders", localId);
    return (record?.data as LocalOrderState) ?? null;
  } catch (cause) {
    console.warn("[rpos] could not read the offline order:", cause);
    return null;
  }
}

/** Bills composed on this device and not yet sold — a reload must not lose them. */
export async function unsold(): Promise<LocalOrderState[]> {
  const db = await database();
  if (!db) return [];

  try {
    const records = await db.getAll("active_orders");
    return records.filter((record) => !record.is_synced).map((record) => record.data as LocalOrderState);
  } catch (cause) {
    console.warn("[rpos] could not read the offline orders:", cause);
    return [];
  }
}

/**
 * Take it off the device once it is queued.
 *
 * The queue entry is the record from here on: keeping a copy in `active_orders`
 * as well would give a paid bill two homes, and the screen would have to decide
 * which one is true.
 */
export async function forget(localId: string): Promise<void> {
  const db = await database();
  try {
    await db?.delete("active_orders", localId);
  } catch (cause) {
    console.warn("[rpos] could not clear the offline order:", cause);
  }
}

/**
 * The day's orders, kept on the device (09 §3, D-080).
 *
 * **A till that cannot show yesterday's bills is not working offline.** Before
 * this, an outage emptied every list: a cashier could sell, but could not look
 * up what was sold — not this morning's, not last week's. For a shop that has
 * been off the line for a day that is the difference between a POS and a
 * notepad.
 *
 * **What is stored is the server's own answer, per view.** Not a local
 * re-derivation of "which orders are closed today": the server decides that
 * (`api/order.VIEWS`, and the day boundary with it), and a second implementation
 * here would drift from it the first time either changed. Each tab's last
 * successful reply is written down and replayed when the line is down.
 *
 * So the mirror is honest about what it is — **a photograph, with a time on
 * it** — and the screen says so rather than presenting stale rows as live ones.
 */

import type { OpenOrder, OrderView } from "@/api/order";

import { database } from "./db";

/** One row per view, in the store `09` §3 set aside for exactly this. */
const KEY = "orders:";

export interface MirroredOrders {
  orders: OpenOrder[];
  /** When this answer came from the server. */
  cached_at: string;
}

export async function remember(view: OrderView, orders: OpenOrder[]): Promise<void> {
  const db = await database();
  if (!db) return;

  try {
    await db.put("config_cache", {
      key: KEY + view,
      data: orders,
      cached_at: new Date().toISOString(),
    });
  } catch (cause) {
    // The list is on screen either way; what is lost is having it during the
    // next outage. Worth a line, not worth interrupting a sale.
    console.warn("[rpos] could not mirror the orders:", cause);
  }
}

export async function recall(view: OrderView): Promise<MirroredOrders | null> {
  const db = await database();
  if (!db) return null;

  try {
    const row = await db.get("config_cache", KEY + view);
    if (!row) return null;

    return { orders: row.data as OpenOrder[], cached_at: row.cached_at };
  } catch (cause) {
    console.warn("[rpos] could not read the mirrored orders:", cause);
    return null;
  }
}

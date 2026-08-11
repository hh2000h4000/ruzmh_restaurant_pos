/**
 * The terminal configuration, kept so the app can start without a server
 * (09 §3, §4).
 *
 * A till that reboots during an outage — the power blinks, someone closes the
 * lid — must come back with its menu, its layout and its permissions. Without
 * this the cashier gets a setup screen and a shift that cannot continue.
 *
 * What is cached is exactly what `load_pos_session` returned. It is not merged,
 * patched or partially refreshed: a half-updated menu is harder to reason about
 * than a wholly stale one, and the payload is small enough to rewrite whole.
 *
 * Refs: 09 §3, §4, FR-1.3
 */

import type { CatalogItem, PosSession } from "@/types/session";

import { database } from "./db";

const CONFIG_KEY = "session";

/** Items live in their own store per 09 §3, so the config row stays small. */
type SessionWithoutItems = Omit<PosSession, "items">;

export async function saveSession(payload: PosSession): Promise<void> {
  const db = await database();
  if (!db) return;

  const cached_at = new Date().toISOString();
  const { items, ...rest } = payload;

  try {
    const tx = db.transaction(["config_cache", "item_cache"], "readwrite");
    await tx.objectStore("config_cache").put({ key: CONFIG_KEY, data: rest, cached_at });

    const store = tx.objectStore("item_cache");
    await store.clear();
    for (const item of items) {
      await store.put({ item_code: item.item_code, data: item, cached_at });
    }

    await tx.done;
  } catch (cause) {
    // A terminal that cannot cache still works online. Losing the cache is a
    // degraded restart, not a failed sale.
    console.warn("[rpos] could not cache the session:", cause);
  }
}

export interface CachedSession {
  session: PosSession;
  cached_at: string;
}

export async function loadSession(): Promise<CachedSession | null> {
  const db = await database();
  if (!db) return null;

  try {
    const config = await db.get("config_cache", CONFIG_KEY);
    if (!config) return null;

    const items = await db.getAll("item_cache");

    return {
      session: {
        ...(config.data as SessionWithoutItems),
        items: items.map((row) => row.data as CatalogItem),
      },
      cached_at: config.cached_at,
    };
  } catch (cause) {
    console.warn("[rpos] could not read the cached session:", cause);
    return null;
  }
}

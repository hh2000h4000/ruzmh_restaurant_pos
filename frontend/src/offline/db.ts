/**
 * The terminal's durable storage (09 §3).
 *
 * Two things matter more than the schema:
 *
 * 1. **IndexedDB may not be there.** Private browsing, a locked-down kiosk
 *    profile, or a user who cleared site data all produce a database that
 *    refuses to open. Every function here answers `null` instead of throwing,
 *    and the app degrades to online-only rather than failing to start
 *    (`CLAUDE.md` §4.7).
 * 2. **The store names come from the spec**, so a later slice can add the
 *    offline order mirror without renaming anything.
 *
 * Refs: 09 §3, CLAUDE.md §4.7
 */

import { openDB, type DBSchema, type IDBPDatabase } from "idb";

const DB_NAME = "rpos_db";
const DB_VERSION = 1;

export interface CachedConfig {
  key: string;
  data: unknown;
  cached_at: string;
}

export interface CachedItem {
  item_code: string;
  data: unknown;
  cached_at: string;
}

/** The order mirror. Written by a later slice; the store exists from v1 so
 *  adding it does not force a version bump on a live terminal. */
export interface LocalOrder {
  local_id: string;
  server_id: string | null;
  status: string;
  data: unknown;
  last_modified: string;
  is_synced: boolean;
}

export type QueueStatus = "pending" | "syncing" | "failed";

export interface QueueEntry {
  queue_id: string;
  created_at: string;
  /** The real API path, e.g. `order.add_item`. See the note in `queue.ts`. */
  path: string;
  payload: Record<string, unknown>;
  retry_count: number;
  status: QueueStatus;
  error_message: string | null;
}

interface RposSchema extends DBSchema {
  config_cache: { key: string; value: CachedConfig };
  item_cache: { key: string; value: CachedItem };
  active_orders: { key: string; value: LocalOrder };
  offline_queue: {
    key: string;
    value: QueueEntry;
    indexes: { by_created: string };
  };
}

export type RposDB = IDBPDatabase<RposSchema>;

let connection: Promise<RposDB | null> | null = null;

/** Resolves to `null` when this browser will not give us a database. */
export function database(): Promise<RposDB | null> {
  if (connection) return connection;

  connection = openDB<RposSchema>(DB_NAME, DB_VERSION, {
    upgrade(db) {
      db.createObjectStore("config_cache", { keyPath: "key" });
      db.createObjectStore("item_cache", { keyPath: "item_code" });
      db.createObjectStore("active_orders", { keyPath: "local_id" });

      const queue = db.createObjectStore("offline_queue", { keyPath: "queue_id" });
      // The flush replays in the order the cashier acted, so this index is not
      // a convenience — out of order, a void could arrive before its item.
      queue.createIndex("by_created", "created_at");
    },
  }).catch((cause) => {
    console.warn("[rpos] no offline storage on this device:", cause);
    return null;
  });

  return connection;
}

/**
 * Ask the browser not to throw this away (D-079).
 *
 * **By default every byte here is "best effort".** Under disk pressure a
 * browser evicts an origin's IndexedDB and caches without asking — which for
 * this app means the menu, the cached session, the app shell **and any offline
 * sale still waiting in the queue**. Money taken and then deleted by a
 * housekeeping routine.
 *
 * `persist()` moves the origin to durable storage, which is not evicted
 * automatically. Chrome grants it silently to an installed app or a site the
 * user visits often, and refuses it for a passing tab — which is the real
 * reason the manifest exists (`D-079`): **installing the terminal is what makes
 * its storage safe.**
 *
 * Called once at start-up. A refusal is worth knowing about and is not worth
 * stopping for; the app works either way, it is only less protected.
 */
export async function requestDurableStorage(): Promise<boolean> {
  if (!navigator.storage?.persist) return false;

  try {
    // Already granted on a previous run — asking again would prompt for nothing.
    if (await navigator.storage.persisted()) return true;

    const granted = await navigator.storage.persist();
    if (!granted) {
      console.warn(
        "[rpos] this browser may delete offline data under disk pressure. " +
          "Install the app (browser menu → Install) so it does not.",
      );
    }
    return granted;
  } catch (cause) {
    console.warn("[rpos] could not ask for durable storage:", cause);
    return false;
  }
}

/** For tests and for sign-out: drop everything this device remembers. */
export async function clearAll(): Promise<void> {
  const db = await database();
  if (!db) return;

  try {
    await Promise.all([
      db.clear("config_cache"),
      db.clear("item_cache"),
      db.clear("active_orders"),
      db.clear("offline_queue"),
    ]);
  } catch (cause) {
    console.warn("[rpos] could not clear offline storage:", cause);
  }
}

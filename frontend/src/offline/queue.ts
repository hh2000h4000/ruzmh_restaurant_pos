/**
 * The offline queue (09 §5, §7).
 *
 * **What gets queued is narrow on purpose.** Only a request that never reached
 * the server is worth keeping: it is the one case where retrying can still
 * succeed. Anything the server answered — a refusal, a permission error, a
 * validation failure — is final, and replaying it forever would turn one bad
 * request into a permanent alarm (`D-027`).
 *
 * **The queue replays the real endpoints**, not a parallel `api.sync.*`
 * namespace as sketched in 09 §7. Every write already accepts a `queue_id` and
 * `POS Sync Entry` already refuses a replay (`utils/idempotency.py`), so a
 * second set of endpoints would be a second implementation of the same rules —
 * and the two would drift. Replaying the original call is provably the same
 * path the online cashier took.
 *
 * Refs: 09 §5, §7, §8, D-027, D-034
 */

import { ApiError, newQueueId, sendQueued } from "@/api/client";

import { database, type QueueEntry } from "./db";

/** 09 §3. After this many failed attempts a human has to look at it. */
const MAX_RETRIES = 5;

export interface Queued {
  readonly queued: true;
  readonly queue_id: string;
}

export function isQueued(value: unknown): value is Queued {
  return typeof value === "object" && value !== null && (value as Queued).queued === true;
}

/**
 * A write that survives the network going away mid-request.
 *
 * Returns the server's answer when there is one, and a `Queued` marker when
 * there is not. The caller has to handle both, which is deliberate: a screen
 * that cannot honestly say "saved here, not yet on the server" should use
 * `mutate` and fail instead of pretending.
 */
export async function mutateOrQueue<T>(
  path: string,
  payload: Record<string, unknown> = {},
): Promise<T | Queued> {
  const queueId = newQueueId();

  try {
    return await sendQueued<T>(path, payload, queueId);
  } catch (cause) {
    // A page with no CSRF token reports itself as offline so the cashier gets a
    // readable message, but the network is fine and the request is malformed —
    // queueing it would replay something that can never succeed.
    if (cause instanceof ApiError && cause.isOffline && cause.exception !== "CSRFTokenMissing") {
      return enqueue(path, payload, queueId);
    }
    throw cause;
  }
}

export async function enqueue(
  path: string,
  payload: Record<string, unknown>,
  queueId: string = newQueueId(),
): Promise<Queued> {
  const db = await database();
  const entry: QueueEntry = {
    queue_id: queueId,
    created_at: new Date().toISOString(),
    path,
    payload,
    retry_count: 0,
    status: "pending",
    error_message: null,
  };

  if (db) {
    try {
      await db.put("offline_queue", entry);
    } catch (cause) {
      // Nothing else can be done here: the write already failed on the network
      // and now cannot be stored either. Say so loudly rather than pretend.
      console.error("[rpos] could not queue an action:", cause);
    }
  }

  return { queued: true, queue_id: queueId };
}

async function entries(): Promise<QueueEntry[]> {
  const db = await database();
  if (!db) return [];

  try {
    return await db.getAllFromIndex("offline_queue", "by_created");
  } catch (cause) {
    console.warn("[rpos] could not read the offline queue:", cause);
    return [];
  }
}

/**
 * Sales taken on this device that the server has not seen yet (D-075).
 *
 * A bill paid offline leaves no `Restaurant Order` to list — it is one queue
 * entry until the connection returns. Without this the cashier takes money,
 * goes to look for the bill, and finds nothing: the most alarming thing a till
 * can do, and the surest way to be paid twice for one meal.
 */
export async function queuedSales(): Promise<QueueEntry[]> {
  return (await entries()).filter((entry) => entry.path === "offline.submit_order");
}

export async function pendingCount(): Promise<number> {
  return (await entries()).filter((entry) => entry.status !== "failed").length;
}

export async function failedCount(): Promise<number> {
  return (await entries()).filter((entry) => entry.status === "failed").length;
}

export interface FlushResult {
  sent: number;
  failed: number;
  /** True when the flush stopped because the connection went away again. */
  interrupted: boolean;
}

let flushing = false;

/**
 * Replay everything pending, oldest first, one at a time.
 *
 * Sequential and ordered is not a performance oversight: a void replayed before
 * the item it voids fails, and two writes to the same order racing each other
 * is how a total ends up wrong. The first network failure stops the run — the
 * connection is gone again and the rest would only burn retries.
 */
export async function flush(): Promise<FlushResult> {
  const result: FlushResult = { sent: 0, failed: 0, interrupted: false };
  if (flushing) return result;

  const db = await database();
  if (!db) return result;

  flushing = true;
  try {
    for (const entry of await entries()) {
      if (entry.status === "failed") continue;

      try {
        await db.put("offline_queue", { ...entry, status: "syncing" });
        await sendQueued(entry.path, entry.payload, entry.queue_id);

        // Success is recorded on the server in `POS Sync Entry`, which is the
        // durable audit trail; keeping a second copy here would grow without
        // bound and answer no question the server cannot.
        await db.delete("offline_queue", entry.queue_id);
        result.sent += 1;
      } catch (cause) {
        const stop = await recordFailure(entry, cause);
        result.failed += stop.givenUp ? 1 : 0;

        if (stop.offline) {
          result.interrupted = true;
          break;
        }
      }
    }
  } finally {
    flushing = false;
  }

  return result;
}

async function recordFailure(
  entry: QueueEntry,
  cause: unknown,
): Promise<{ offline: boolean; givenUp: boolean }> {
  const db = await database();
  const error = cause instanceof ApiError ? cause : null;
  const offline = error?.isOffline ?? false;

  // A 4xx is the server's considered answer — it will be the same answer next
  // week. A 5xx might be a bad minute on the bench, so that one is retried.
  const permanent = error !== null && !offline && error.status < 500;
  const retries = offline ? entry.retry_count : entry.retry_count + 1;
  const givenUp = permanent || retries >= MAX_RETRIES;

  await db?.put("offline_queue", {
    ...entry,
    retry_count: retries,
    status: givenUp ? "failed" : "pending",
    error_message: cause instanceof Error ? cause.message : String(cause),
  });

  return { offline, givenUp };
}

/** Everything a human has to deal with by hand (09 §10, "SYNC FAILED"). */
export async function failedEntries(): Promise<QueueEntry[]> {
  return (await entries()).filter((entry) => entry.status === "failed");
}

export async function discard(queueId: string): Promise<void> {
  const db = await database();
  try {
    await db?.delete("offline_queue", queueId);
  } catch (cause) {
    console.warn("[rpos] could not discard a queue entry:", cause);
  }
}

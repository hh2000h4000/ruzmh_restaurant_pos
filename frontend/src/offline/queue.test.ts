/**
 * The queue decides whether a cashier's action is retried, abandoned, or sent
 * twice. Every branch below has a way of losing or duplicating money.
 *
 * Refs: 09 §5, §7, §8, D-027, D-034
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";

const sendQueued = vi.hoisted(() => vi.fn());

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  sendQueued,
}));

const { clearAll, database } = await import("./db");
const { enqueue, failedCount, flush, mutateOrQueue, pendingCount } = await import("./queue");

const offline = () => new ApiError("no connection", 0, "TypeError: failed to fetch");
const refused = (status: number) => new ApiError("refused", status, "PermissionError");

beforeEach(async () => {
  sendQueued.mockReset();
  await clearAll();
});

afterEach(async () => {
  await clearAll();
});

describe("mutateOrQueue", () => {
  it("returns the server's answer when there is one", async () => {
    sendQueued.mockResolvedValue({ order_name: "RO-1" });

    const result = await mutateOrQueue("order.cancel_order", { order_name: "RO-1" });

    expect(result).toEqual({ order_name: "RO-1" });
    expect(await pendingCount()).toBe(0);
  });

  it("keeps a request that never reached the server", async () => {
    sendQueued.mockRejectedValue(offline());

    const result = await mutateOrQueue("order.cancel_order", { order_name: "RO-1" });

    expect(result).toMatchObject({ queued: true });
    expect(await pendingCount()).toBe(1);
  });

  it("does not keep a refusal — the answer will be the same next week (D-027)", async () => {
    sendQueued.mockRejectedValue(refused(403));

    await expect(mutateOrQueue("order.cancel_order", {})).rejects.toThrow();
    expect(await pendingCount()).toBe(0);
  });

  it("does not keep a request the page could never have sent", async () => {
    // A missing CSRF token reports itself as offline so the cashier gets a
    // readable message. Queueing it would replay a malformed request forever.
    sendQueued.mockRejectedValue(new ApiError("no token", 0, "CSRFTokenMissing"));

    await expect(mutateOrQueue("order.cancel_order", {})).rejects.toThrow();
    expect(await pendingCount()).toBe(0);
  });

  it("sends the same queue_id it stored, so a replay cannot act twice", async () => {
    sendQueued.mockRejectedValueOnce(offline());
    const queued = await mutateOrQueue<unknown>("order.cancel_order", { order_name: "RO-1" });

    sendQueued.mockResolvedValue({});
    await flush();

    const [, , replayedId] = sendQueued.mock.calls.at(-1) ?? [];
    expect(replayedId).toBe((queued as { queue_id: string }).queue_id);
  });
});

describe("flush", () => {
  it("replays in the order the cashier acted", async () => {
    await enqueue("order.add_item", { item: "first" }, "q-1");
    // Distinct timestamps: the index orders by `created_at`, and two entries
    // written in the same millisecond would make this test lie.
    await new Promise((resolve) => setTimeout(resolve, 2));
    await enqueue("order.add_item", { item: "second" }, "q-2");

    sendQueued.mockResolvedValue({});
    await flush();

    expect(sendQueued.mock.calls.map((call) => call[1])).toEqual([
      { item: "first" },
      { item: "second" },
    ]);
  });

  it("forgets an entry once the server has it", async () => {
    await enqueue("order.cancel_order", {}, "q-1");
    sendQueued.mockResolvedValue({});

    const result = await flush();

    expect(result.sent).toBe(1);
    expect(await pendingCount()).toBe(0);
  });

  it("gives up immediately on a refusal instead of retrying five times", async () => {
    await enqueue("order.cancel_order", {}, "q-1");
    sendQueued.mockRejectedValue(refused(417));

    await flush();

    expect(sendQueued).toHaveBeenCalledTimes(1);
    expect(await failedCount()).toBe(1);
    expect(await pendingCount()).toBe(0);
  });

  it("retries a server error, because a bad minute on the bench passes", async () => {
    await enqueue("order.cancel_order", {}, "q-1");
    sendQueued.mockRejectedValue(new ApiError("boom", 500));

    await flush();

    expect(await pendingCount()).toBe(1);
    const db = await database();
    expect((await db?.get("offline_queue", "q-1"))?.retry_count).toBe(1);
  });

  it("gives up on a server error that will not stop", async () => {
    await enqueue("order.cancel_order", {}, "q-1");
    sendQueued.mockRejectedValue(new ApiError("boom", 500));

    for (let attempt = 0; attempt < 5; attempt += 1) await flush();

    expect(await failedCount()).toBe(1);
  });

  it("stops at the first outage rather than burning the rest of the queue", async () => {
    await enqueue("order.add_item", { item: "first" }, "q-1");
    await new Promise((resolve) => setTimeout(resolve, 2));
    await enqueue("order.add_item", { item: "second" }, "q-2");

    sendQueued.mockRejectedValue(offline());
    const result = await flush();

    expect(result.interrupted).toBe(true);
    expect(sendQueued).toHaveBeenCalledTimes(1);
    // An outage is not the entry's fault: nothing was counted against it.
    const db = await database();
    expect((await db?.get("offline_queue", "q-1"))?.retry_count).toBe(0);
    expect(await pendingCount()).toBe(2);
  });

  it("leaves a failed entry alone on later runs", async () => {
    await enqueue("order.cancel_order", {}, "q-1");
    sendQueued.mockRejectedValue(refused(403));
    await flush();

    sendQueued.mockClear();
    sendQueued.mockResolvedValue({});
    await flush();

    expect(sendQueued).not.toHaveBeenCalled();
  });
});

// @vitest-environment jsdom

/**
 * What order the list comes in (`D-161`).
 *
 * The user's instruction was one line — *"always start from the newest"* — and
 * acting on it exposed a second thing beside it: the list sorted by when a bill
 * **opened**, whichever tab was showing. On the floor that is right and is why
 * it was written that way (`06` Screen 1: the bill that has waited longest is
 * the one needing attention). On *closed today* it is the `D-146` mistake one
 * layer up — a bill opened at eleven and paid at one lands at the wrong end of
 * "today" — and it quietly undid the order the server had already put the rows
 * in.
 *
 * So two things are held here: the default, and the moment each row is sorted
 * by — which is the same moment the row prints under its number.
 */
import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as orderApi from "@/api/order";
import type { OpenOrder } from "@/api/order";
import { useOpenOrders } from "@/composables/useOpenOrders";
import { useConnectionStore } from "@/stores/connection";
import { useOrderStore } from "@/stores/order";
import { useSessionStore } from "@/stores/session";
import type { PosSession } from "@/types/session";

vi.mock("@/api/order", () => ({
  listOrders: vi.fn(),
  searchOrders: vi.fn(),
  // Driven for real in "when the list refetches": the chain under test is
  // cancel -> the store's `run` -> `settledAt` -> the list asking again.
  cancelOrder: vi.fn(),
}));
vi.mock("@/offline/orderMirror", () => ({
  recall: vi.fn(),
  remember: vi.fn(),
  warm: vi.fn(),
}));
vi.mock("@/offline/queue", () => ({
  queuedSales: vi.fn().mockResolvedValue([]),
  // The store asks whether an answer was deferred rather than performed; here
  // the server is up, so every answer is a real one.
  isQueued: vi.fn().mockReturnValue(false),
}));

function bill(extra: Partial<OpenOrder>): OpenOrder {
  return {
    name: "RO-1",
    daily_number: 1,
    status: "active",
    total_amount: 10,
    opened_at: "2026-09-07 10:00:00",
    closed_at: null,
    item_count: 1,
    ...extra,
  } as OpenOrder;
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
});

/** The list as the server hands it over, read back in the order it is shown. */
async function shown(rows: OpenOrder[], sort?: "oldest" | "newest") {
  useSessionStore().data = { pos_profile: { name: "T1" } } as unknown as PosSession;
  vi.mocked(orderApi.listOrders).mockResolvedValue(rows);

  const floor = useOpenOrders();
  if (sort) floor.sort.value = sort;
  await floor.refresh();

  return { floor, names: floor.visible.value.map((row) => row.name) };
}

describe("the order the list comes in", () => {
  it("starts from the newest, on whichever tab", () => {
    expect(useOpenOrders().sort.value).toBe("newest");
  });

  /**
   * The bill paid a minute ago is the one a cashier came to this tab for —
   * however long ago it was opened.
   */
  it("sorts a closed bill by when it closed, not when it opened", async () => {
    // Chosen so the two orderings disagree: this one was **opened first** and
    // **closed last** — a table that sat down before midnight and settled after
    // the morning rush. Sorted by `opened_at` it goes to the bottom.
    const longTab = bill({
      name: "RO-LONG-TAB",
      opened_at: "2026-09-06 23:40:00",
      closed_at: "2026-09-07 08:30:00",
      status: "closed",
    });
    const quick = bill({
      name: "RO-QUICK",
      opened_at: "2026-09-07 08:00:00",
      closed_at: "2026-09-07 08:10:00",
      status: "closed",
    });

    // **The sort is named rather than left to the default.** With both left
    // implicit, breaking the key *and* the default cancelled out and this test
    // passed on a screen that was wrong twice — which a mutation run caught and
    // an eye would not have.
    const { names } = await shown([quick, longTab], "newest");

    expect(names).toEqual(["RO-LONG-TAB", "RO-QUICK"]);
  });

  it("sorts an open bill by when it opened, because it has no other moment", async () => {
    const { names } = await shown([
      bill({ name: "RO-OLD", opened_at: "2026-09-07 09:00:00" }),
      bill({ name: "RO-NEW", opened_at: "2026-09-07 11:00:00" }),
    ]);

    expect(names).toEqual(["RO-NEW", "RO-OLD"]);
  });

  it("still turns round when the cashier asks for the oldest", async () => {
    const { names } = await shown(
      [
        bill({ name: "RO-NEW", opened_at: "2026-09-07 11:00:00" }),
        bill({ name: "RO-OLD", opened_at: "2026-09-07 09:00:00" }),
      ],
      "oldest",
    );

    expect(names).toEqual(["RO-OLD", "RO-NEW"]);
  });
});

/**
 * When the list asks the server again (`D-180`).
 *
 * The user cancelled an open bill and watched the row sit there for seconds:
 * *"المفترض فوري يتم حذف الصف من القائمة"*. Nothing told the list — it polls
 * every fifteen seconds, and that interval was doing double duty as the only
 * notice of the cashier's **own** actions. Polling answers what the other
 * terminals did; it is the wrong instrument for what this hand just did.
 *
 * These hold the wiring both ways: a mutation asks again at once, and a burst
 * of them does not turn into a burst of requests.
 */
describe("when the list refetches", () => {
  /** A mounted list, so the store's signal is actually being watched. */
  async function floorOnScreen() {
    useSessionStore().data = { pos_profile: { name: "T1" } } as unknown as PosSession;
    vi.mocked(orderApi.listOrders).mockResolvedValue([]);

    const floor = useOpenOrders();
    await floor.refresh();
    vi.mocked(orderApi.listOrders).mockClear();
    return floor;
  }

  it("asks again the moment an order changes", async () => {
    await floorOnScreen();

    // What every mutation in the store does when it comes back without
    // throwing — cancelling a bill among them.
    useOrderStore().settledAt += 1;
    await flushPromises();

    expect(orderApi.listOrders).toHaveBeenCalledOnce();
  });

  it("a cancelled bill takes the row off the floor at once", async () => {
    const floor = await floorOnScreen();
    const store = useOrderStore();
    store.order = { order_name: "RO-1" } as never;
    vi.mocked(orderApi.cancelOrder).mockResolvedValue({ order_name: "RO-1" } as never);
    // The bill is gone from the server's answer, which is the whole point.
    vi.mocked(orderApi.listOrders).mockResolvedValue([]);

    await store.cancel("wrong table");
    await flushPromises();

    expect(orderApi.listOrders).toHaveBeenCalledOnce();
    expect(floor.visible.value).toEqual([]);
  });

  it("asks again when the action was refused, because the refusal says we are wrong", async () => {
    // **This reverses what the first version of `D-180` asserted here.** It
    // said a refused action changed nothing, so there was nothing to fetch.
    // Nothing changed *on the server* — but "that order is already cancelled"
    // is another terminal's work arriving as an error, and the row it names is
    // still on this screen. The refusal is the best reason to ask again.
    const floor = await floorOnScreen();
    const store = useOrderStore();
    store.order = { order_name: "RO-1" } as never;
    vi.mocked(orderApi.cancelOrder).mockRejectedValue(
      new Error("Order RO-1 is already cancelled."),
    );
    vi.mocked(orderApi.listOrders).mockResolvedValue([]);

    await store.cancel("changed my mind");
    await flushPromises();

    expect(orderApi.listOrders).toHaveBeenCalledOnce();
    expect(floor.visible.value).toEqual([]);
  });

  it("does not chase a server that is not there", async () => {
    // Offline the list is already drawing the device's own copy, and a request
    // to a dead server costs a timeout to learn nothing.
    await floorOnScreen();
    useConnectionStore().state = "offline";
    const store = useOrderStore();

    store.settledAt += 1;
    await flushPromises();

    expect(orderApi.listOrders).not.toHaveBeenCalled();
  });

  it("collapses a second change during a fetch into one follow-up", async () => {
    const floor = await floorOnScreen();
    const store = useOrderStore();

    let release: (rows: never[]) => void = () => {};
    vi.mocked(orderApi.listOrders).mockReturnValueOnce(
      new Promise((resolve) => {
        release = resolve as (rows: never[]) => void;
      }),
    );

    store.settledAt += 1;
    await flushPromises();
    expect(orderApi.listOrders).toHaveBeenCalledOnce();

    // A second action lands while the first answer is still on its way. Without
    // coalescing this starts a second request racing the first, and the list
    // draws whichever returns last.
    store.settledAt += 1;
    await flushPromises();
    expect(orderApi.listOrders).toHaveBeenCalledOnce();

    vi.mocked(orderApi.listOrders).mockResolvedValue([]);
    release([]);
    await flushPromises();

    // Exactly one follow-up, and it is the one that sees everything.
    expect(orderApi.listOrders).toHaveBeenCalledTimes(2);
    expect(floor.visible.value).toEqual([]);
  });
});
